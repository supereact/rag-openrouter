import { defineConfig } from "@neon/config/v1";

export default defineConfig({
  buckets: {
    "rag-documents": { access: "private" },
    "rag-uploads": { access: "private" },
  },
});
