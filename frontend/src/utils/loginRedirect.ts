// Where a successful login goes: shared by the email login (LoginPage) and the
// Google login's callback page, which gets the same context back from before
// it left for Google (utils/googleAuth.ts).

export interface LoginRedirectState {
  // Where the user was headed when they got sent to the login page.
  returnTo: string | null;
  // Whether they had a session that ended, and whose (set by AuthExpiryRedirect).
  sessionEnded: boolean;
  expiredUserId: string | null;
}

// Only an in-app absolute path is honored, never anything that could leave the app.
export function getRedirectState(state: unknown): LoginRedirectState {
  const { returnTo, sessionEnded, userId } = (state ?? {}) as {
    returnTo?: unknown;
    sessionEnded?: unknown;
    userId?: unknown;
  };
  const safe =
    typeof returnTo === "string" && returnTo.startsWith("/") && !returnTo.startsWith("//") && !returnTo.startsWith("/login");
  return {
    returnTo: safe ? returnTo : null,
    sessionEnded: sessionEnded === true,
    expiredUserId: typeof userId === "string" ? userId : null,
  };
}

// Back to the page the ended session was on, but only for that same account:
// someone else signing in there would land on a page that isn't theirs. If a
// session had ended but whose is unknown (it began before the id was
// remembered), it isn't taken back either.
export function destinationAfterLogin(redirect: LoginRedirectState, signedInUserId: string | null): string {
  const sameAccount =
    !redirect.sessionEnded || (redirect.expiredUserId !== null && signedInUserId === redirect.expiredUserId);
  return sameAccount ? (redirect.returnTo ?? "/") : "/";
}
