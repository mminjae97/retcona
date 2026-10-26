import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { migrateLegacyStorage, schedulePruneStaleDrafts } from "./utils/draft";
import "./styles/theme.css";

migrateLegacyStorage();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

schedulePruneStaleDrafts();
