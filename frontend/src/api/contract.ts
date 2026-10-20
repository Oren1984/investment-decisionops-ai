/** Request contracts generated from the FastAPI OpenAPI document (`npm run gen:api`; see scripts/check).
 * Responses are plain dicts on the backend, so response types stay hand-written in ./types.ts. */
import type { components } from "./schema";

export type Body<K extends keyof components["schemas"]> = components["schemas"][K];
