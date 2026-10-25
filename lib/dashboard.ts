import { ApiError, getStaffProfile } from "@/lib/api";

// Decides which dashboard a signed-in user should see.
// Staff go to their staff dashboard. If the API says the user is not a staff
// member (403 or 404), they are a voter. Any other problem is passed on.
export async function getDashboardPath(): Promise<string> {
  try {
    const staff = await getStaffProfile();

    return staff.role === "admin"
      ? "/staff/admin/dashboard"
      : "/staff/employee/dashboard";
  } catch (error) {
    if (
      error instanceof ApiError &&
      (error.status === 403 || error.status === 404)
    ) {
      return "/voter/dashboard";
    }

    throw error;
  }
}
