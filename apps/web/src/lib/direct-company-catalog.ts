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
  {
    id: "csem",
    name: "CSEM",
    careersUrl: "https://www.csem.ch/en/jobs/",
    logoSrc: "/company-logos/csem.svg",
    logoAlt: "CSEM logo",
    logoWidth: 40,
    logoHeight: 24,
  },
  {
    id: "deloitte",
    name: "Deloitte",
    careersUrl: "https://apply.deloitte.ch/CHCareers/",
    logoSrc: "/company-logos/deloitte.svg",
    logoAlt: "Deloitte logo",
    logoWidth: 40,
    logoHeight: 24,
  },
  {
    id: "zuercher_kantonalbank",
    name: "Zürcher Kantonalbank",
    careersUrl: "https://apply.refline.ch/792841/search.html",
    logoSrc: "/company-logos/zuercher_kantonalbank.svg",
    logoAlt: "Zürcher Kantonalbank logo",
    logoWidth: 48,
    logoHeight: 24,
  },
  {
    id: "flughafen_zuerich",
    name: "Flughafen Zürich",
    careersUrl:
      "https://www.flughafen-zuerich.ch/de/unternehmen/jobs/karriere/stellenangebote",
    logoSrc: "/company-logos/flughafen_zuerich.svg",
    logoAlt: "Flughafen Zürich logo",
    logoWidth: 96,
    logoHeight: 12,
  },
  {
    id: "ubs_students_graduates",
    name: "UBS Students & Graduates",
    careersUrl:
      "https://jobs.ubs.com/TGnewUI/Search/home/HomeWithPreLoad?partnerid=25008&siteid=5131&PageType=searchResults&SearchType=linkquery&LinkID=15232#keyWordSearch=&locationSearch=Switzerland",
    logoSrc: "/company-logos/ubs.svg",
    logoAlt: "UBS logo",
    logoWidth: 64,
    logoHeight: 23,
  },
  {
    id: "abb_switzerland",
    name: "ABB Schweiz",
    careersUrl:
      "https://careers.abb/global/en/search-results?rk=l-abb-switzerland-careers&sortBy=Most%20relevant",
    logoSrc: "/company-logos/abb.svg",
    logoAlt: "ABB Schweiz logo",
    logoWidth: 64,
    logoHeight: 24,
  },
  {
    id: "huawei_switzerland",
    name: "Huawei Switzerland",
    careersUrl: "https://careers.huaweirc.ch/jobs",
    logoSrc: "/company-logos/huawei.svg",
    logoAlt: "Huawei Switzerland logo",
    logoWidth: 32,
    logoHeight: 24,
  },
  {
    id: "bdo_switzerland",
    name: "BDO Switzerland",
    careersUrl: "https://www.bdo.ch/en-gb/careers/open-jobs",
    logoSrc: "/company-logos/bdo.svg",
    logoAlt: "BDO Switzerland logo",
    logoWidth: 48,
    logoHeight: 19,
  },
  {
    id: "ey_switzerland",
    name: "EY Switzerland",
    careersUrl:
      "https://careers.ey.com/ey/search/?createNewAlert=false&q=&locationsearch=&optionsFacetsDD_country=CH&optionsFacetsDD_customfield1=",
    logoSrc: "/company-logos/ey.svg",
    logoAlt: "EY Switzerland logo",
    logoWidth: 24,
    logoHeight: 24,
  },
  {
    id: "eth_zurich",
    name: "ETH Zürich",
    careersUrl: "https://jobs.ethz.ch/",
    logoSrc: "/company-logos/eth_zurich.svg",
    logoAlt: "ETH Zürich logo",
    logoWidth: 96,
    logoHeight: 16,
  },
  {
    id: "siemens_switzerland",
    name: "Siemens Schweiz",
    careersUrl:
      "https://jobs.siemens.com/de_DE/externaljobs/SearchJobs/?42386=%5B812129%5D&42386_format=17546&listFilterMode=1&folderRecordsPerPage=6",
    logoSrc: "/company-logos/siemens.svg",
    logoAlt: "Siemens Schweiz logo",
    logoWidth: 88,
    logoHeight: 14,
  },
];

export function getDirectCompanyByJobId(jobId: string) {
  return directCompanyCatalog.find((company) =>
    jobId.startsWith(`${company.id}-`),
  );
}
