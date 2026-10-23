import { ApiError, publicApiRequest } from "./api";

// A receipt only proves a ballot was recorded. It never says who the ballot was for.

export type ReceiptRecord = {
  recordedAt: string;
  includedInTally: boolean;
};

// Receipt format: 4 groups of 4 characters, e.g. "7KQ2-M9XD-4RTA-H8WC"
// Must match backend/receipts.py.
export const RECEIPT_GROUPS = 4;
export const RECEIPT_GROUP_LENGTH = 4;
export const RECEIPT_LENGTH = RECEIPT_GROUPS * RECEIPT_GROUP_LENGTH;

// Letters and numbers only, without look-alikes (0/O, 1/I/L)
export const RECEIPT_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ";

// Looks the receipt up on the backend. Returns null when no ballot matches.
// The backend rate-limits lookups so receipt codes cannot be guessed.
export async function verifyReceipt(receipt: string): Promise<ReceiptRecord | null> {
  try {
    return await publicApiRequest<ReceiptRecord>("/api/public/receipts/verify", {
      method: "POST",
      body: JSON.stringify({ receipt }),
    });
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}
