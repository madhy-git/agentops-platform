// Quick-start topics for a new request. They only pre-fill the message: the platform decides the category from
// what the customer writes (triage + rules), so picking "Something else" for a stolen card still reaches fraud.
import { CreditCard, HandHeart, MessageSquareWarning, ReceiptText, ShieldAlert, type LucideIcon } from "lucide-react";

export type Topic = { id: string; title: string; text: string; icon: LucideIcon; template: string };

export const TOPICS: Topic[] = [
  {
    id: "card",
    title: "Lost or stolen card",
    text: "Block your card and stop unknown charges",
    icon: ShieldAlert,
    template: "My card was stolen and I can see charges I didn't make.",
  },
  {
    id: "dispute",
    title: "Dispute a transaction",
    text: "Query a charge you don't recognise",
    icon: ReceiptText,
    template: "I want to dispute a transaction on my card that I don't recognise.",
  },
  {
    id: "hardship",
    title: "Financial hardship",
    text: "Talk to us about repayments",
    icon: HandHeart,
    template: "I lost my job and I can't make this month's loan repayment.",
  },
  {
    id: "complaint",
    title: "Make a complaint",
    text: "Tell us what went wrong",
    icon: MessageSquareWarning,
    template: "I want to make a complaint about how my issue was handled.",
  },
  {
    id: "other",
    title: "Something else",
    text: "Fees, statements, cards",
    icon: CreditCard,
    template: "",
  },
];
