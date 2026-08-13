import { describe, expect, it } from "vitest";

import {
  directCompanyCatalog,
  getDirectCompanyByJobId,
} from "@/lib/direct-company-catalog";

describe("InfoGuard Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "infoguard",
    );

    expect(company).toEqual({
      id: "infoguard",
      name: "InfoGuard",
      careersUrl: "https://www.infoguard.ch/en/career",
      logoSrc: "/company-logos/infoguard.svg",
      logoAlt: "InfoGuard logo",
      logoWidth: 143,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("infoguard-incident-responder")).toBe(
      company,
    );
  });
});

describe("Dätwyler IT Infra Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "datwyler_it_infra",
    );

    expect(company).toEqual({
      id: "datwyler_it_infra",
      name: "Dätwyler IT Infra",
      careersUrl:
        "https://careers.datwyler-itinfra.com/search/?locale=de_DE&searchResultView=LIST&facetFilters=%7B%22jobLocationCountry%22%3A%5B%22Schweiz%22%5D%7D&pageNumber=0",
      logoSrc: "/company-logos/datwyler_it_infra.svg",
      logoAlt: "Dätwyler IT Infra logo",
      logoWidth: 113,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("datwyler_it_infra-432")).toBe(company);
  });
});

describe("Edorex Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find((item) => item.id === "edorex");

    expect(company).toEqual({
      id: "edorex",
      name: "Edorex",
      careersUrl: "https://edorex.ch/jobs",
      logoSrc: "/company-logos/edorex.svg",
      logoAlt: "Edorex logo",
      logoWidth: 62,
      logoHeight: 24,
    });
    expect(
      getDirectCompanyByJobId("edorex-senior-postgresql-consultant-mwd"),
    ).toBe(company);
  });
});

describe("Centris Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find((item) => item.id === "centris");

    expect(company).toEqual({
      id: "centris",
      name: "Centris",
      careersUrl: "https://www.centrisag.ch/karriere/jobs",
      logoSrc: "/company-logos/centris.svg",
      logoAlt: "Centris logo",
      logoWidth: 99,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("centris-1085")).toBe(company);
  });
});

describe("Sika Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "sika_switzerland",
    );

    expect(company).toEqual({
      id: "sika_switzerland",
      name: "Sika Switzerland",
      careersUrl: "https://www.sika.com/en/career/jobs.html",
      logoSrc: "/company-logos/sika.svg",
      logoAlt: "Sika Switzerland logo",
      logoWidth: 32,
      logoHeight: 28,
    });
    expect(
      getDirectCompanyByJobId(
        "sika_switzerland-9c76864a-9d47-46eb-af82-10893fcfc91e",
      ),
    ).toBe(company);
  });
});

describe("Swiss Life Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "swiss_life_switzerland",
    );

    expect(company).toEqual({
      id: "swiss_life_switzerland",
      name: "Swiss Life Switzerland",
      careersUrl: "https://www.swisslife.ch/de/ueber-uns/karriere/jobs.html#",
      logoSrc: "/company-logos/swiss_life.svg",
      logoAlt: "Swiss Life Switzerland logo",
      logoWidth: 96,
      logoHeight: 24,
    });
    expect(
      getDirectCompanyByJobId(
        "swiss_life_switzerland-4c6b891f-22b1-494c-ad4e-06a25ede7ef4",
      ),
    ).toBe(company);
  });
});

describe("Teradata Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "teradata_switzerland",
    );

    expect(company).toEqual({
      id: "teradata_switzerland",
      name: "Teradata Switzerland",
      careersUrl: "https://careers.teradata.com/jobs",
      logoSrc: "/company-logos/teradata.svg",
      logoAlt: "Teradata Switzerland logo",
      logoWidth: 120,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("teradata_switzerland-220353")).toBe(
      company,
    );
  });
});

describe("NTT Global Data Centers Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "ntt_global_data_centers_switzerland",
    );

    expect(company).toEqual({
      id: "ntt_global_data_centers_switzerland",
      name: "NTT Global Data Centers",
      careersUrl:
        "https://nttglobaldatacenters.wd501.myworkdayjobs.com/en-US/External/jobs?locations=0416448655001000c28517e560890000",
      logoSrc: "/company-logos/ntt_global_data_centers.svg",
      logoAlt: "NTT Global Data Centers logo",
      logoWidth: 87,
      logoHeight: 24,
    });
    expect(
      getDirectCompanyByJobId("ntt_global_data_centers_switzerland-jr101121"),
    ).toBe(company);
  });
});

describe("Nexplore Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find((item) => item.id === "nexplore");

    expect(company).toEqual({
      id: "nexplore",
      name: "Nexplore",
      careersUrl: "https://www.nexplore.ch/jobs",
      logoSrc: "/company-logos/nexplore.svg",
      logoAlt: "Nexplore logo",
      logoWidth: 112,
      logoHeight: 24,
    });
    expect(
      getDirectCompanyByJobId("nexplore-bcff2b26-bae2-48e2-851d-f39ee1fbcb3d"),
    ).toBe(company);
  });
});

describe("Bedag Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find((item) => item.id === "bedag");

    expect(company).toEqual({
      id: "bedag",
      name: "Bedag",
      careersUrl: "https://www.bedag.ch/de/jobs-und-karriere/offene-stellen/",
      logoSrc: "/company-logos/bedag.svg",
      logoAlt: "Bedag logo",
      logoWidth: 101,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("bedag-1008")).toBe(company);
  });
});

describe("ALSO Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find((item) => item.id === "also");

    expect(company).toEqual({
      id: "also",
      name: "ALSO",
      careersUrl:
        "https://www.also.com/ec/cms5/en_6000/6000/company/career/open-positions/index.jsp",
      logoSrc: "/company-logos/also.svg",
      logoAlt: "ALSO logo",
      logoWidth: 120,
      logoHeight: 19,
    });
    expect(getDirectCompanyByJobId("also-296512")).toBe(company);
  });
});

describe("Georg Fischer Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "georg_fischer_switzerland",
    );

    expect(company).toEqual({
      id: "georg_fischer_switzerland",
      name: "Georg Fischer Switzerland",
      careersUrl:
        "https://georgfischer.wd103.myworkdayjobs.com/GeorgFischer_Careers?locationCountry=187134fccb084a0ea9b4b95f23890dbe",
      logoSrc: "/company-logos/georg_fischer.svg",
      logoAlt: "Georg Fischer Switzerland logo",
      logoWidth: 75,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("georg_fischer_switzerland-jr10784")).toBe(
      company,
    );
  });
});

describe("Bachem Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find((item) => item.id === "bachem");

    expect(company).toEqual({
      id: "bachem",
      name: "Bachem",
      careersUrl:
        "https://careers.bachem.com/search/?createNewAlert=false&q=&optionsFacetsDD_department=&optionsFacetsDD_shifttype=&optionsFacetsDD_location=&optionsFacetsDD_country=CH&optionsFacetsDD_customfield1=",
      logoSrc: "/company-logos/bachem.svg",
      logoAlt: "Bachem logo",
      logoWidth: 87,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("bachem-1425152933")).toBe(company);
  });
});

describe("Maerki Baumann Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "maerki_baumann",
    );

    expect(company).toEqual({
      id: "maerki_baumann",
      name: "Maerki Baumann",
      careersUrl:
        "https://www.maerki-baumann.ch/de/unsere-bank/stellenangebote",
      logoSrc: "/company-logos/maerki_baumann.svg",
      logoAlt: "Maerki Baumann logo",
      logoWidth: 18,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("maerki_baumann-78216")).toBe(company);
  });
});

describe("Electrosuisse Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "electrosuisse",
    );

    expect(company).toEqual({
      id: "electrosuisse",
      name: "Electrosuisse",
      careersUrl: "https://www.electrosuisse.ch/de/karriere/offene-stellen/",
      logoSrc: "/company-logos/electrosuisse.svg",
      logoAlt: "Electrosuisse logo",
      logoWidth: 43,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("electrosuisse-80275")).toBe(company);
  });
});

describe("Detecon Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "detecon_switzerland",
    );

    expect(company).toEqual({
      id: "detecon_switzerland",
      name: "Detecon Switzerland",
      careersUrl: "https://www.detecon.com/de/jobs",
      logoSrc: "/company-logos/detecon.svg",
      logoAlt: "Detecon Switzerland logo",
      logoWidth: 128,
      logoHeight: 24,
    });
    expect(
      getDirectCompanyByJobId(
        "detecon_switzerland-student-consultant-applied-agentic-ai-entwicklung-all-genders",
      ),
    ).toBe(company);
  });
});

describe("Lufthansa Group Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "lufthansa_group_switzerland",
    );

    expect(company).toEqual({
      id: "lufthansa_group_switzerland",
      name: "Lufthansa Group Switzerland",
      careersUrl:
        "https://apply.lufthansagroup.careers/index.php?ac=search_result&search_criterion_division%5B%5D=5926&search_criterion_division%5B%5D=9114&search_criterion_division%5B%5D=5988&search_criterion_division%5B%5D=6006&search_criterion_channel%5B%5D=12",
      logoSrc: "/company-logos/lufthansa_group.svg",
      logoAlt: "Lufthansa Group Switzerland logo",
      logoWidth: 132,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("lufthansa_group_switzerland-134020")).toBe(
      company,
    );
  });
});

describe("Adesso Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "adesso_switzerland",
    );

    expect(company).toEqual({
      id: "adesso_switzerland",
      name: "Adesso Switzerland",
      careersUrl:
        "https://www.adesso.ch/de_ch/jobs-karriere/unsere-stellenangebote/",
      logoSrc: "/company-logos/adesso.svg",
      logoAlt: "Adesso Switzerland logo",
      logoWidth: 64,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("adesso_switzerland-2956")).toBe(company);
  });
});

describe("Cudos Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find((item) => item.id === "cudos");

    expect(company).toEqual({
      id: "cudos",
      name: "Cudos",
      careersUrl: "https://cudos.ch/de/jobs/",
      logoSrc: "/company-logos/cudos.svg",
      logoAlt: "Cudos logo",
      logoWidth: 144,
      logoHeight: 24,
    });
    expect(
      getDirectCompanyByJobId("cudos-senior-software-engineer-c-sharp"),
    ).toBe(company);
  });
});

describe("Eraneos Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "eraneos_switzerland",
    );

    expect(company).toEqual({
      id: "eraneos_switzerland",
      name: "Eraneos Switzerland",
      careersUrl:
        "https://eraneos.wd3.myworkdayjobs.com/Eraneos_External_Career_Site",
      logoSrc: "/company-logos/eraneos.svg",
      logoAlt: "Eraneos Switzerland logo",
      logoWidth: 154,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("eraneos_switzerland-jr100169")).toBe(
      company,
    );
  });
});

describe("ERNI Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "erni_switzerland",
    );

    expect(company).toEqual({
      id: "erni_switzerland",
      name: "ERNI Switzerland",
      careersUrl: "https://www.betterask.erni/ch-en/job-opportunities/",
      logoSrc: "/company-logos/erni.svg",
      logoAlt: "ERNI Switzerland logo",
      logoWidth: 92,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("erni_switzerland-7852745")).toBe(company);
  });
});

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

describe("Stadler IT Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "stadler_it_switzerland",
    );

    expect(company).toEqual({
      id: "stadler_it_switzerland",
      name: "Stadler IT Switzerland",
      careersUrl:
        "https://www.stadlerrail.com/de/karriere/offene-stellen?10=1077445&25=1098730&",
      logoSrc: "/company-logos/stadler.svg",
      logoAlt: "Stadler IT Switzerland logo",
      logoWidth: 142,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("stadler_it_switzerland-10133279")).toBe(
      company,
    );
  });
});

describe("EBP Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "ebp_switzerland",
    );

    expect(company).toEqual({
      id: "ebp_switzerland",
      name: "EBP Switzerland",
      careersUrl:
        "https://www.ebp.global/ch-de/karriere/offene-stellen/stellenangebote",
      logoSrc: "/company-logos/ebp.svg",
      logoAlt: "EBP Switzerland logo",
      logoWidth: 79,
      logoHeight: 24,
    });
    expect(
      getDirectCompanyByJobId(
        "ebp_switzerland-b913f9ef-1bdc-4824-8b46-ea0607c12c58",
      ),
    ).toBe(company);
  });
});

describe("RUAG Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "ruag_switzerland",
    );

    expect(company).toEqual({
      id: "ruag_switzerland",
      name: "RUAG Switzerland",
      careersUrl: "https://www.ruag.ch/en/working-us/job-portal",
      logoSrc: "/company-logos/ruag.svg",
      logoAlt: "RUAG Switzerland logo",
      logoWidth: 40,
      logoHeight: 24,
    });
    expect(
      getDirectCompanyByJobId(
        "ruag_switzerland-24e02ed3-4dc6-4358-a9f4-9383b380371b",
      ),
    ).toBe(company);
  });
});

describe("Cyberlink Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "cyberlink",
    );

    expect(company).toEqual({
      id: "cyberlink",
      name: "Cyberlink",
      careersUrl: "https://www.cyberlink.ch/de/cyberlink/jobs",
      logoSrc: "/company-logos/cyberlink.svg",
      logoAlt: "Cyberlink logo",
      logoWidth: 118,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("cyberlink-spontanbewerbung")).toBe(company);
  });
});

describe("Ergon Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find((item) => item.id === "ergon");

    expect(company).toEqual({
      id: "ergon",
      name: "Ergon",
      careersUrl: "https://www.ergon.ch/de/karriere/jobs?showAllJobs=true",
      logoSrc: "/company-logos/ergon.svg",
      logoAlt: "Ergon logo",
      logoWidth: 82,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("ergon-2587674")).toBe(company);
  });
});

describe("LogObject Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "logobject",
    );

    expect(company).toEqual({
      id: "logobject",
      name: "LogObject",
      careersUrl: "https://logobject.com/karriere",
      logoSrc: "/company-logos/logobject.svg",
      logoAlt: "LogObject logo",
      logoWidth: 116,
      logoHeight: 24,
    });
    expect(
      getDirectCompanyByJobId(
        "logobject-wirtschaftsinformatiker-software-entwicklung-m-w-d-1",
      ),
    ).toBe(company);
  });
});

describe("ti&m Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "ti8m_switzerland",
    );

    expect(company).toEqual({
      id: "ti8m_switzerland",
      name: "ti&m Switzerland",
      careersUrl: "https://www.ti8m.com/en/career#job",
      logoSrc: "/company-logos/ti8m.svg",
      logoAlt: "ti&m Switzerland logo",
      logoWidth: 65,
      logoHeight: 24,
    });
    expect(
      getDirectCompanyByJobId(
        "ti8m_switzerland-cc7debd9-6eea-40f0-9c48-6a8152ca5227",
      ),
    ).toBe(company);
  });
});

describe("Novartis Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "novartis_switzerland",
    );

    expect(company).toEqual({
      id: "novartis_switzerland",
      name: "Novartis Switzerland",
      careersUrl:
        "https://www.novartis.com/careers/career-search?search_api_fulltext=&country%5B%5D=LOC_CH&field_job_posted_date=All&op=Submit",
      logoSrc: "/company-logos/novartis.svg",
      logoAlt: "Novartis Switzerland logo",
      logoWidth: 160,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("novartis_switzerland-req-10084379")).toBe(
      company,
    );
  });
});

describe("Pictet Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "pictet_switzerland",
    );

    expect(company).toEqual({
      id: "pictet_switzerland",
      name: "Pictet Switzerland",
      careersUrl:
        "https://career012.successfactors.eu/career?company=banquepict&career_ns=job_listing_summary&navBarLevel=JOB_SEARCH",
      logoSrc: "/company-logos/pictet.svg",
      logoAlt: "Pictet Switzerland logo",
      logoWidth: 108,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("pictet_switzerland-124439")).toBe(company);
  });
});
