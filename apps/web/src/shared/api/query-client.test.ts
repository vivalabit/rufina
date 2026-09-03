import { describe, expect, it } from "vitest";

import { createQueryClient } from "./query-client";

describe("API query client", () => {
  it("does not replay query functions outside the method-aware transport", async () => {
    const queryClient = createQueryClient();
    let calls = 0;

    await expect(queryClient.fetchQuery({
      queryKey: ["unsafe-mixed-query"],
      queryFn: async () => {
        calls += 1;
        throw new Error("failed after a legacy import");
      },
    })).rejects.toThrow("failed after a legacy import");

    expect(calls).toBe(1);
  });
});
