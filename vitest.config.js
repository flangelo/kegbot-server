import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["pykeg/web/static/js/**/*.test.js"],
  },
});
