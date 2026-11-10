"""Start-up is safe when several pods start at once (Kubernetes: 2 API replicas + 1 worker).

LEARNING NOTE: without db.startup_lock, this test fails intermittently with duplicate-key errors on
schema_migrations, because every thread sees "001 not applied" and tries to apply it. Races are the bugs
you only find by actually running things concurrently; a single-process test suite never would.
"""

import threading
import uuid

from agentops import db


def test_concurrent_startup_migrates_exactly_once():
    schema = f"test_startup_{uuid.uuid4().hex[:8]}"
    admin = db.connect()
    admin.execute(f'CREATE SCHEMA "{schema}"')
    results: list[list[str]] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(4)  # release all four "pods" at the same instant

    def pod() -> None:
        conn = db.connect(schema=schema)
        try:
            barrier.wait()
            with db.startup_lock(conn):
                results.append(db.migrate(conn))
        except BaseException as e:  # collected and asserted below; a thread's exception is otherwise lost
            errors.append(e)
        finally:
            conn.close()

    try:
        threads = [threading.Thread(target=pod) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        applied = [r for r in results if r]
        assert len(applied) == 1, "exactly one pod applies the migrations; the rest find them done"
        assert sum(len(r) for r in results) == len(applied[0])
    finally:
        admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        admin.close()
