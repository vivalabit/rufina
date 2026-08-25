import { describe, expect, it } from "vitest";

import { parseJobDescription } from "@/lib/job-description";

describe("parseJobDescription", () => {
  it("turns flattened LinkedIn sections into headings and lists", () => {
    const sections = parseJobDescription(
      "Overview We build useful software. Our products support teams every day. " +
        "Aufgaben Als Mitglied des Teams arbeitest du am Frontend. " +
        "Deine Aufgaben Du entwickelst Webanwendungen Du arbeitest mit UX an einem Design System Du achtest auf Clean Code " +
        "Qualifikation Deine Qualifikationen Du hast Erfahrung mit TypeScript Du sprichst Deutsch und Englisch " +
        "Benefits Feste Ansprechperson im Team Code Reviews und Pair Programming Direkter Einblick in Product und Requirements Engineering, nicht nur Tickets abarbeiten " +
        "Zusätzliche Informationen Viel Eigenverantwortung und abwechslungsreiche Aufgaben sowie Home Office Show more Show less",
    );

    expect(sections.map((section) => section.heading)).toEqual([
      undefined,
      "Aufgaben",
      "Deine Aufgaben",
      "Deine Qualifikationen",
      "Benefits",
      "Zusätzliche Informationen",
    ]);
    expect(sections[2].items).toEqual([
      "Du entwickelst Webanwendungen",
      "Du arbeitest mit UX an einem Design System",
      "Du achtest auf Clean Code",
    ]);
    expect(sections[4].items).toEqual([
      "Feste Ansprechperson im Team",
      "Code Reviews und Pair Programming",
      "Direkter Einblick in Product und Requirements Engineering, nicht nur Tickets abarbeiten",
    ]);
    expect(sections[5].paragraphs).toEqual([
      "Viel Eigenverantwortung und abwechslungsreiche Aufgaben sowie Home Office",
    ]);
  });

  it("preserves explicit source lines as list items", () => {
    const sections = parseJobDescription(
      "About the job\nA growing product team.\n\nYour main tasks\nPick orders\nPack products\nCheck quality\n\nYour profile\nReliable\nCareful",
    );

    expect(sections[0]).toMatchObject({
      heading: undefined,
      paragraphs: ["A growing product team."],
    });
    expect(sections[1]).toMatchObject({
      heading: "Your main tasks",
      items: ["Pick orders", "Pack products", "Check quality"],
    });
    expect(sections[2]).toMatchObject({
      heading: "Your profile",
      items: ["Reliable", "Careful"],
    });
  });

  it("breaks long plain prose into readable paragraphs", () => {
    const sentence = "This sentence explains an important part of the vacancy in enough detail to make the text substantial.";
    const sections = parseJobDescription(`${sentence} ${sentence} ${sentence} ${sentence}`);

    expect(sections).toHaveLength(1);
    expect(sections[0].paragraphs.length).toBeGreaterThan(1);
  });
});
