import { describe, expect, it } from "vitest";

import {
  directCompanyCatalog,
  getDirectCompanyByJobId,
} from "@/lib/direct-company-catalog";

describe("Huber+Suhner Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "huber_suhner_switzerland",
    );

    expect(company).toEqual({
      id: "huber_suhner_switzerland",
      name: "Huber+Suhner Switzerland",
      careersUrl: "https://recruiting.hubersuhner.com/Jobs/All",
      logoSrc: "/company-logos/huber_suhner.svg",
      logoAlt: "Huber+Suhner Switzerland logo",
      logoWidth: 92,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("huber_suhner_switzerland-7806")).toBe(
      company,
    );
  });
});
