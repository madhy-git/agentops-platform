// Customer help assistant: answers from customer-readable articles only (the FAQ), with citations.
// Questions about internal policy get "raise a request", never a hint that internal documents exist.
import { Link } from "react-router-dom";
import { Chat } from "../../components/Chat";
import { Card, PageHeader } from "../../components/ui";

export default function Help() {
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="Help"
        subtitle={
          <>
            Answers come from our help articles. For anything about your own account,{" "}
            <Link to="/portal/new" className="font-medium text-brand-700 underline-offset-2 hover:underline dark:text-brand-300">
              raise a request
            </Link>
            .
          </>
        }
      />
      <Card className="p-4 sm:p-6">
        <Chat
          endpoint="/portal/assistant/stream"
          emptyTitle="Ask us anything about cards, fees and statements"
          emptyText="Answers are drawn from Wattle Bank's help articles, with the source shown."
          placeholder="e.g. How much is the foreign transaction fee?"
          suggestions={[
            "How much is the foreign transaction fee?",
            "How do I download my statements?",
            "Can I lock my card in the app?",
            "How is credit card interest calculated?",
          ]}
        />
      </Card>
    </div>
  );
}
