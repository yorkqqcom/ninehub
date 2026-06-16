import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import router from "./router";
import "@vue-flow/core/dist/style.css";
import "@vue-flow/core/dist/theme-default.css";
import "./styles/tokens.css";
import "./styles/theme-light.css";
import "./styles/theme-dark.css";
import "./styles/base.css";
import "./styles/layout.css";
import "./styles/login.css";
import "./styles/components.css";

const app = createApp(App);
app.use(createPinia());
app.use(router);
app.mount("#app");
