// Mock receipt records for the Verify receipt page.
// A receipt only proves a ballot was recorded. It never says who the ballot was for.
// TODO: remove this and look receipts up on the backend instead.

export type ReceiptRecord = {
  recordedAt: string;
  includedInTally: boolean;
};

// Receipt format: 4 groups of 4 characters, e.g. "7KQ2-M9XD-4RTA-H8WC"
export const RECEIPT_GROUPS = 4;
export const RECEIPT_GROUP_LENGTH = 4;
export const RECEIPT_LENGTH = RECEIPT_GROUPS * RECEIPT_GROUP_LENGTH;

// Letters and numbers only, without look-alikes (0/O, 1/I/L)
export const RECEIPT_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ";

export const MOCK_RECEIPTS: Record<string, ReceiptRecord> = {
  "7KQ2M9XD4RTAH8WC": { recordedAt: "2026-10-17T10:42:00+11:00", includedInTally: true },
  "P3VN6BZE2JUFK5SY": { recordedAt: "2026-10-17T14:05:00+11:00", includedInTally: true },
};
