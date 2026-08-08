export type DirectCompanyDefinition = {
  id: string;
  name: string;
  careersUrl: string;
  logoSrc: string;
  logoAlt: string;
  logoWidth?: number;
  logoHeight?: number;
};

// Add companies here only after their matching backend parser is registered.
export const directCompanyCatalog: readonly DirectCompanyDefinition[] = [
  {
    id: "sbb",
    name: "SBB CFF FFS",
    careersUrl:
      "https://company.sbb.ch/de/jobs-karriere/jobs/offene-stellen.html?startItem=1",
    logoSrc: "/company-logos/sbb.svg",
    logoAlt: "SBB CFF FFS logo",
    logoWidth: 32,
    logoHeight: 24,
  },
  {
    id: "swisscom",
    name: "Swisscom",
    careersUrl:
      "https://swisscom.wd103.myworkdayjobs.com/en-US/SwisscomExternalCareers",
    logoSrc: "/company-logos/swisscom.svg",
    logoAlt: "Swisscom logo",
    logoWidth: 24,
    logoHeight: 24,
  },
  {
    id: "galaxus",
    name: "Galaxus",
    careersUrl: "https://jobs.migros.ch/de/unsere-unternehmen/galaxus/",
    logoSrc: "/company-logos/galaxus.svg",
    logoAlt: "Galaxus logo",
    logoWidth: 24,
    logoHeight: 24,
  },
  {
    id: "migros_bank",
    name: "Migros Bank",
    careersUrl:
      "https://jobs.migros.ch/de/unsere-unternehmen/migros-bank/offene-stellen",
    logoSrc: "/company-logos/migros_bank.svg",
    logoAlt: "Migros Bank logo",
    logoWidth: 36,
    logoHeight: 32,
  },
  {
    id: "die_post",
    name: "Die Post",
    careersUrl: "https://job.post.ch/search?locale=en_US",
    logoSrc: "/company-logos/die_post.svg",
    logoAlt: "Die Post logo",
    logoWidth: 24,
    logoHeight: 24,
  },
  {
    id: "raiffeisen",
    name: "Raiffeisen",
    careersUrl: "https://jobs.raiffeisen.ch/",
    logoSrc: "/company-logos/raiffeisen.svg",
    logoAlt: "Raiffeisen logo",
    logoWidth: 24,
    logoHeight: 32,
  },
  {
    id: "bundesverwaltung",
    name: "Bundesverwaltung",
    careersUrl: "https://jobs.admin.ch/?lang=de",
    logoSrc: "/company-logos/bundesverwaltung.svg",
    logoAlt: "Bundesverwaltung logo",
    logoWidth: 32,
    logoHeight: 32,
  },
  {
    id: "axa_schweiz",
    name: "AXA Schweiz",
    careersUrl:
      "https://careers.axa.com/careers-home/jobs?country=Switzerland&page=1",
    logoSrc: "/company-logos/axa_schweiz.svg",
    logoAlt: "AXA Schweiz logo",
    logoWidth: 32,
    logoHeight: 32,
  },
  {
    id: "sunrise",
    name: "Sunrise",
    careersUrl: "https://careers.sunrise.ch/gb/en/search-results",
    logoSrc: "/company-logos/sunrise.png",
    logoAlt: "Sunrise logo",
    logoWidth: 32,
    logoHeight: 16,
  },
  {
    id: "iss",
    name: "ISS Schweiz",
    careersUrl: "https://www.ch.issworld.com/de-ch/karriere/offene-stellen",
    logoSrc: "/company-logos/iss.svg",
    logoAlt: "ISS Schweiz logo",
    logoWidth: 32,
    logoHeight: 28,
  },
  {
    id: "accenture",
    name: "Accenture",
    careersUrl: "https://www.accenture.com/ch-en/careers/jobsearch",
    logoSrc: "/company-logos/accenture.svg",
    logoAlt: "Accenture logo",
    logoWidth: 32,
    logoHeight: 24,
  },
];

export function getDirectCompanyByJobId(jobId: string) {
  return directCompanyCatalog.find((company) =>
    jobId.startsWith(`${company.id}-`),
  );
}
