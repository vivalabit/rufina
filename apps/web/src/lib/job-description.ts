export type JobDescriptionSection = {
  heading?: string;
  paragraphs: string[];
  items: string[];
};

const sectionHeadings = [
  "Additional information",
  "Zusätzliche Informationen",
  "What you will do",
  "What you'll do",
  "What we offer",
  "What we are looking for",
  "Your responsibilities",
  "Key responsibilities",
  "Your qualifications",
  "Deine Qualifikationen",
  "Ihre Qualifikationen",
  "Das zeichnet dich aus",
  "Das bringst du mit",
  "Das bieten wir dir",
  "Deine Aufgaben",
  "Ihre Aufgaben",
  "Your main tasks",
  "Your profile",
  "Ihr Profil",
  "Über uns",
  "About the job",
  "About us",
  "The role",
  "Your role",
  "Responsibilities",
  "Requirements",
  "Qualifications",
  "Qualifikation",
  "Aufgaben",
  "Benefits",
  "Wir bieten Ihnen",
  "Wir bieten",
  "Weitere Informationen",
  "Overview",
];

const listHeadingPattern = /(?:aufgaben|responsibilit|requirements|qualifikation|qualifications|profil|profile|bringst du mit|zeichnet dich aus|benefits|bieten|offer|main tasks|what you|your role)/i;

const listItemStarters = [
  "Feste Ansprechperson",
  "Code Reviews",
  "Direkter Einblick",
  "AI-gestützte",
  "Erfahrung mit",
  "Flexibilität und Freiraum",
  "Job und Familie",
  "Vorsorge und Versicherungen",
  "Flexible Benefits",
  "Gesunde Balance",
  "Eigeninitiative",
  "Analytisches Denkvermögen",
  "Teamgeist",
  "Du entwickelst",
  "Du arbeitest",
  "Du achtest",
  "Du bringst",
  "Du nutzt",
  "Du schätzt",
  "Du sprichst",
  "Du bist",
  "Du hast",
  "Sie entwickeln",
  "Sie arbeiten",
  "Sie bringen",
  "Sie verfügen",
  "You will",
  "You are",
  "You have",
  "Your experience",
  "Strong",
  "Excellent",
];

const hiddenOverviewHeadings = new Set(["Overview", "About the job"]);

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function normalizeDescriptionText(value: string) {
  return value
    .replace(/\r/g, "")
    .replace(/\s*(?:Show more Show less|Mehr anzeigen Weniger anzeigen)\s*$/i, "")
    .trim();
}

function splitReadableParagraphs(value: string) {
  const explicitParagraphs = value
    .split(/\n\s*\n+/)
    .flatMap((paragraph) => paragraph.split(/\n+/))
    .map((paragraph) => paragraph.replace(/\s+/g, " ").trim())
    .filter(Boolean);

  return explicitParagraphs.flatMap((paragraph) => {
    const sentences = paragraph
      .split(/(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Þ0-9])/u)
      .map((sentence) => sentence.trim())
      .filter(Boolean);

    if (sentences.length < 2) return [paragraph];

    const grouped: string[] = [];
    let current = "";

    for (const sentence of sentences) {
      if (current && `${current} ${sentence}`.length > 320) {
        grouped.push(current);
        current = sentence;
      } else {
        current = current ? `${current} ${sentence}` : sentence;
      }
    }

    if (current) grouped.push(current);
    return grouped;
  });
}

function splitListItems(value: string) {
  const explicitLines = value
    .split(/\n+/)
    .map((line) => line.replace(/^[•*\-–—]\s*/, "").replace(/\s+/g, " ").trim())
    .filter(Boolean);

  if (explicitLines.length >= 2) {
    return explicitLines;
  }

  const starterPattern = new RegExp(
    `(^|\\s)(${listItemStarters.map(escapeRegExp).join("|")})(?=\\s|$)`,
    "g",
  );
  const matches = Array.from(value.matchAll(starterPattern));

  if (matches.length < 2) return [];

  const items: string[] = [];
  const firstMatchIndex = (matches[0].index ?? 0) + (matches[0][1]?.length ?? 0);
  const preamble = value.slice(0, firstMatchIndex).replace(/\s+/g, " ").trim();
  if (preamble) items.push(preamble);

  for (let index = 0; index < matches.length; index += 1) {
    const match = matches[index];
    const start = (match.index ?? 0) + (match[1]?.length ?? 0);
    const nextMatch = matches[index + 1];
    const end = nextMatch
      ? (nextMatch.index ?? value.length) + (nextMatch[1]?.length ?? 0)
      : value.length;
    const item = value.slice(start, end).replace(/\s+/g, " ").trim();
    if (item) items.push(item);
  }

  return items;
}

function buildSection(heading: string | undefined, body: string): JobDescriptionSection | null {
  const normalizedBody = body.trim();
  if (!normalizedBody) return null;

  const items = heading && listHeadingPattern.test(heading)
    ? splitListItems(normalizedBody)
    : [];

  return {
    heading: heading && !hiddenOverviewHeadings.has(heading) ? heading : undefined,
    paragraphs: items.length >= 2 ? [] : splitReadableParagraphs(normalizedBody),
    items: items.length >= 2 ? items : [],
  };
}

function isLikelySectionHeading(text: string, match: RegExpMatchArray) {
  const heading = match[2];
  const bodyStart = (match.index ?? 0) + match[0].length;
  const followingText = text.slice(bodyStart).trimStart();

  if (!followingText) return true;
  if (/^[a-zäöüß]/u.test(followingText)) return false;
  if (heading === "Requirements" && /^Engineering\b/.test(followingText)) return false;
  return true;
}

export function parseJobDescription(value: string): JobDescriptionSection[] {
  const text = normalizeDescriptionText(value);
  if (!text) return [];

  const headingPattern = new RegExp(
    `(^|\\s)(${sectionHeadings
      .slice()
      .sort((left, right) => right.length - left.length)
      .map(escapeRegExp)
      .join("|")})(?=\\s|$)`,
    "g",
  );
  const matches = Array.from(text.matchAll(headingPattern)).filter((match) =>
    isLikelySectionHeading(text, match),
  );

  if (matches.length === 0) {
    return [{ paragraphs: splitReadableParagraphs(text), items: [] }];
  }

  const sections: JobDescriptionSection[] = [];
  const firstHeadingStart = (matches[0].index ?? 0) + (matches[0][1]?.length ?? 0);
  const introduction = buildSection(undefined, text.slice(0, firstHeadingStart));
  if (introduction) sections.push(introduction);

  for (let index = 0; index < matches.length; index += 1) {
    const match = matches[index];
    const prefixLength = match[1]?.length ?? 0;
    const heading = match[2];
    const bodyStart = (match.index ?? 0) + match[0].length;
    const nextMatch = matches[index + 1];
    const bodyEnd = nextMatch
      ? (nextMatch.index ?? text.length) + (nextMatch[1]?.length ?? 0)
      : text.length;
    const section = buildSection(heading, text.slice(bodyStart, bodyEnd));

    if (section) {
      sections.push(section);
    } else if (prefixLength === 0 && sections.length === 0) {
      sections.push({ heading, paragraphs: [], items: [] });
    }
  }

  return sections;
}
