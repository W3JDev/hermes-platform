import "react-native-get-random-values";
import "@copilotkit/react-native/polyfills";
import { registerRootComponent } from "expo";
import App from "./App";

if (typeof window !== "undefined" && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch((err) => {
      console.warn("ServiceWorker registration failed:", err);
    });
  });
}

registerRootComponent(App);
