export type DirectCompanyDefinition = {
  id: string;
  name: string;
  careersUrl: string;
  logoSrc: string;
  logoAlt: string;
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
  },
];

export function getDirectCompanyByJobId(jobId: string) {
  return directCompanyCatalog.find((company) =>
    jobId.startsWith(`${company.id}-`),
  );
}
