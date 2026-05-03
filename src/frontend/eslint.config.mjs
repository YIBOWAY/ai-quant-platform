import { defineConfig } from "eslint/config";
import next from "eslint-config-next";

export default defineConfig([{
    ignores: [".next/**", "test-results/**", "playwright-report/**"],
    extends: [...next],
}]);
