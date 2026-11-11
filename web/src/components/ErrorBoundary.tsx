// Catches rendering errors so one broken component shows a message instead of blanking the whole page.
//
// LEARNING NOTE: without a boundary, any exception thrown while React renders unmounts the entire app: the user
// sees a white page and the only clue is in the browser console. A boundary turns "it crashed" into an error
// message someone can report. (Errors in event handlers and fetches don't reach it; those are caught where they
// happen and shown with ErrorNote.)
import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button } from "./ui";

type State = { error: Error | null };

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[agentops] render error:", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="mx-auto max-w-xl p-8">
        <div className="rounded-2xl bg-red-50 p-6 ring-1 ring-red-200 dark:bg-red-950/50 dark:ring-red-900">
          <h2 className="font-semibold text-red-800 dark:text-red-200">Something went wrong on this page</h2>
          <p className="mt-2 font-mono text-sm break-words text-red-700 dark:text-red-300">{this.state.error.message}</p>
          <p className="mt-2 text-sm text-red-700/80 dark:text-red-300/80">
            The rest of the app still works. If this keeps happening, share the message above.
          </p>
          <div className="mt-4 flex gap-2">
            <Button onClick={() => this.setState({ error: null })}>Try again</Button>
            <Button variant="secondary" onClick={() => window.location.assign("/")}>
              Go home
            </Button>
          </div>
        </div>
      </div>
    );
  }
}
