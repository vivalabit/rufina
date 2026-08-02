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
    id: "die_post",
    name: "Die Post",
    careersUrl: "https://job.post.ch/search?locale=en_US",
    logoSrc: "/company-logos/die_post.svg",
    logoAlt: "Die Post logo",
    logoWidth: 24,
    logoHeight: 24,
  },
];

export function getDirectCompanyByJobId(jobId: string) {
  return directCompanyCatalog.find((company) =>
    jobId.startsWith(`${company.id}-`),
  );
}
