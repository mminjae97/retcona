// Whether this browser holds a session, kept current as the author moves between
// pages (a login or logout ends in a navigation), and when another tab signs in or
// out or the session expires. Having a token is not proof it still works: a
// session that has ended is found out by the next request (api/client.ts).
import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { getToken, onAuthExpired } from "../api/client";

export function useSignedIn(): boolean {
  const location = useLocation();
  const [signedIn, setSignedIn] = useState(() => getToken() !== null);
  useEffect(() => setSignedIn(getToken() !== null), [location.key]);
  useEffect(() => {
    const refresh = () => setSignedIn(getToken() !== null);
    window.addEventListener("storage", refresh);
    const stopListening = onAuthExpired(refresh);
    return () => {
      window.removeEventListener("storage", refresh);
      stopListening();
    };
  }, []);
  return signedIn;
}
