import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { pruneStaleDrafts } from "./utils/draft";
import "./styles/theme.css";

pruneStaleDrafts();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
