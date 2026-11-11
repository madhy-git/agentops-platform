// Staff policy copilot: streamed, cited answers from the documents YOUR roles may read. Ask about hardship
// options as the officer, then as the hardship specialist: same question, different answer, by design.
import { Lock } from "lucide-react";
import { Chat } from "../../components/Chat";
import { Card, PageHeader } from "../../components/ui";
import { useAuth } from "../../lib/auth";

export default function Copilot() {
  const { session } = useAuth();
  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title="Policy copilot" subtitle={`Answers only from policies ${session?.persona.display_name} is entitled to read.`} />
      <Card className="p-4 sm:p-6">
        <Chat
          // A fresh conversation per person: memory is per user, and switching person shouldn't show old turns.
          key={session?.persona.username}
          endpoint="/copilot/stream"
          emptyTitle="Ask about Wattle Bank policy"
          emptyText="Every answer cites its source. If the best guidance is restricted for your role, you're told which team to refer to, never what it says."
          placeholder="e.g. How long does a customer have to dispute a card transaction?"
          suggestions={[
            "How long does a customer have to dispute a card transaction?",
            "What hardship arrangement options can we offer?",
            "How much is the foreign transaction fee?",
            "How long do we have to respond to a complaint?",
          ]}
          referralNote={(to) => (
            <div className="flex items-start gap-2 rounded-xl bg-amber-50 p-3 text-sm text-amber-900 ring-1 ring-amber-200 dark:bg-amber-950/50 dark:text-amber-200 dark:ring-amber-900">
              <Lock className="mt-0.5 size-4 shrink-0" />
              <span>
                More detailed guidance exists but is restricted for your role. Refer the case to <strong>{to}</strong>.
              </span>
            </div>
          )}
        />
      </Card>
    </div>
  );
}
