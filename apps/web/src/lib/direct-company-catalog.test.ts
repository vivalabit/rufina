import { describe, expect, it } from "vitest";

import {
  directCompanyCatalog,
  getDirectCompanyByJobId,
} from "@/lib/direct-company-catalog";

describe("Gilead Sciences Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "gilead_switzerland",
    );

    expect(company).toEqual({
      id: "gilead_switzerland",
      name: "Gilead Sciences Switzerland",
      careersUrl:
        "https://gilead.wd1.myworkdayjobs.com/gileadcareers?locations=173342972c1201e6f4862b77b074df3b",
      logoSrc: "/company-logos/gilead.svg",
      logoAlt: "Gilead Sciences Switzerland logo",
      logoWidth: 149,
      logoHeight: 40,
    });
    expect(getDirectCompanyByJobId("gilead_switzerland-r0053823")).toBe(
      company,
    );
  });
});

describe("GSK Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "gsk_switzerland",
    );

    expect(company).toEqual({
      id: "gsk_switzerland",
      name: "GSK Switzerland",
      careersUrl:
        "https://jobs.gsk.com/gb/en/search-results?keywords=&location=Switzerland&lang=en-gb",
      logoSrc: "/company-logos/gsk.svg",
      logoAlt: "GSK Switzerland logo",
      logoWidth: 40,
      logoHeight: 40,
    });
    expect(getDirectCompanyByJobId("gsk_switzerland-445481")).toBe(company);
  });
});

describe("Sanofi Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "sanofi_switzerland",
    );

    expect(company).toEqual({
      id: "sanofi_switzerland",
      name: "Sanofi Switzerland",
      careersUrl:
        "https://jobs.sanofi.com/en/search-jobs/Switzerland/2649/2/2658434/47x00016/8x01427/50/2",
      logoSrc: "/company-logos/sanofi.svg",
      logoAlt: "Sanofi Switzerland logo",
      logoWidth: 196,
      logoHeight: 30,
    });
    expect(getDirectCompanyByJobId("sanofi_switzerland-42680975104")).toBe(
      company,
    );
  });
});

describe("Takeda Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "takeda_switzerland",
    );

    expect(company).toEqual({
      id: "takeda_switzerland",
      name: "Takeda Switzerland",
      careersUrl: "https://jobs.takeda.com/search-jobs",
      logoSrc: "/company-logos/takeda.svg",
      logoAlt: "Takeda Switzerland logo",
      logoWidth: 113,
      logoHeight: 40,
    });
    expect(getDirectCompanyByJobId("takeda_switzerland-99191848720")).toBe(
      company,
    );
  });
});

describe("Johnson & Johnson Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "jnj_switzerland",
    );

    expect(company).toEqual({
      id: "jnj_switzerland",
      name: "Johnson & Johnson Switzerland",
      careersUrl:
        "https://www.careers.jnj.com/en/jobs/?search=&country=Switzerland&origin=global",
      logoSrc: "/company-logos/johnson-and-johnson.svg",
      logoAlt: "Johnson & Johnson Switzerland logo",
      logoWidth: 154,
      logoHeight: 15,
    });
    expect(getDirectCompanyByJobId("jnj_switzerland-r-093101")).toBe(company);
  });
});

describe("Zurich Insurance Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "zurich_insurance",
    );

    expect(company).toEqual({
      id: "zurich_insurance",
      name: "Zurich Insurance",
      careersUrl:
        "https://www.careers.zurich.com/search/?createNewAlert=false&q=&locationsearch=zurich&optionsFacetsDD_shifttype=&optionsFacetsDD_department=&optionsFacetsDD_customfield3=",
      logoSrc: "/company-logos/zurich-insurance.svg",
      logoAlt: "Zurich Insurance logo",
      logoWidth: 83,
      logoHeight: 32,
    });
    expect(getDirectCompanyByJobId("zurich_insurance-1369305757")).toBe(
      company,
    );
  });
});

describe("Schneider Electric Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "schneider_electric_switzerland",
    );

    expect(company).toEqual({
      id: "schneider_electric_switzerland",
      name: "Schneider Electric Switzerland",
      careersUrl:
        "https://careers.se.com/jobs?lang=de-DE&country=Switzerland&page=1",
      logoSrc: "/company-logos/schneider-electric.svg",
      logoAlt: "Schneider Electric Switzerland logo",
      logoWidth: 109,
      logoHeight: 32,
    });
    expect(
      getDirectCompanyByJobId("schneider_electric_switzerland-117294"),
    ).toBe(company);
  });
});

describe("Bosch Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "bosch_switzerland",
    );

    expect(company).toEqual({
      id: "bosch_switzerland",
      name: "Bosch Switzerland",
      careersUrl: "https://jobs.bosch.com/en/?pages=1&country=ch#",
      logoSrc: "/company-logos/bosch.svg",
      logoAlt: "Bosch Switzerland logo",
      logoWidth: 143,
      logoHeight: 32,
    });
    expect(getDirectCompanyByJobId("bosch_switzerland-REF293937G")).toBe(
      company,
    );
  });
});

describe("Eviden Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "eviden_switzerland",
    );

    expect(company).toEqual({
      id: "eviden_switzerland",
      name: "Eviden Switzerland",
      careersUrl: "https://eviden.com/careers/?country=CH",
      logoSrc: "/company-logos/eviden.svg",
      logoAlt: "Eviden Switzerland logo",
      logoWidth: 160,
      logoHeight: 32,
    });
    expect(getDirectCompanyByJobId("eviden_switzerland-550075")).toBe(
      company,
    );
  });
});

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

describe("Komax Group Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "komax_group",
    );

    expect(company).toEqual({
      id: "komax_group",
      name: "Komax Group",
      careersUrl:
        "https://jobs.komaxgroup.com/search/?q=&locationsearch=switzerland&searchResultView=LIST&pageNumber=0&facetFilters=%7B%7D&sortBy=&markerViewed=&carouselIndex=",
      logoSrc: "/company-logos/komax-group.svg",
      logoAlt: "Komax Group logo",
      logoWidth: 88,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("komax_group-2157")).toBe(company);
  });
});

describe("BearingPoint Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "bearingpoint_switzerland",
    );

    expect(company).toEqual({
      id: "bearingpoint_switzerland",
      name: "BearingPoint Switzerland",
      careersUrl:
        "https://www.bearingpoint.com/de-ch/karriere/stellenangebote/?country=CH",
      logoSrc: "/company-logos/bearingpoint.svg",
      logoAlt: "BearingPoint Switzerland logo",
      logoWidth: 120,
      logoHeight: 20,
    });
    expect(getDirectCompanyByJobId("bearingpoint_switzerland-T7760115")).toBe(
      company,
    );
  });
});

describe("Julius Baer Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "julius_baer_switzerland",
    );

    expect(company).toEqual({
      id: "julius_baer_switzerland",
      name: "Julius Baer Switzerland",
      careersUrl:
        "https://juliusbaer.wd3.myworkdayjobs.com/en-US/External?Location_Country=187134fccb084a0ea9b4b95f23890dbe",
      logoSrc: "/company-logos/julius-baer.svg",
      logoAlt: "Julius Baer Switzerland logo",
      logoWidth: 121,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("julius_baer_switzerland-r-19350")).toBe(
      company,
    );
  });
});

describe("BKW Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "bkw_switzerland",
    );

    expect(company).toEqual({
      id: "bkw_switzerland",
      name: "BKW Switzerland",
      careersUrl: "https://jobs.bkw.com/en/vacancies",
      logoSrc: "/company-logos/bkw.svg",
      logoAlt: "BKW Switzerland logo",
      logoWidth: 66,
      logoHeight: 24,
    });
    expect(
      getDirectCompanyByJobId(
        "bkw_switzerland-974955bb-343b-44e5-bfa9-af77587ef35d",
      ),
    ).toBe(company);
  });
});

describe("Swiss National Bank Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find((item) => item.id === "snb");

    expect(company).toEqual({
      id: "snb",
      name: "Swiss National Bank (SNB)",
      careersUrl: "https://careers.snb.ch/search/?locale=de_DE",
      logoSrc: "/company-logos/snb.svg",
      logoAlt: "Swiss National Bank logo",
      logoWidth: 146,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("snb-3453")).toBe(company);
  });
});

describe("AMAG Group Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "amag_group",
    );

    expect(company).toEqual({
      id: "amag_group",
      name: "AMAG Group",
      careersUrl: "https://jobs.amag-group.ch/",
      logoSrc: "/company-logos/amag-group.svg",
      logoAlt: "AMAG Group logo",
      logoWidth: 19,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("amag_group-23412")).toBe(company);
  });
});

describe("Bayer Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "bayer_switzerland",
    );

    expect(company).toEqual({
      id: "bayer_switzerland",
      name: "Bayer Switzerland",
      careersUrl:
        "https://talent.bayer.com/careers?location=Basel%2CBasel-City%2CSwitzerland&pid=562949977567067&job%20type=professional&job%20type=job%20starter&job%20type=student&job%20type=graduate&domain=bayer.com&sort_by=relevance&triggerGoButton=false",
      logoSrc: "/company-logos/bayer.svg",
      logoAlt: "Bayer Switzerland logo",
      logoWidth: 24,
      logoHeight: 24,
    });
    expect(
      getDirectCompanyByJobId("bayer_switzerland-562949978313882"),
    ).toBe(company);
  });
});

describe("Biogen Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "biogen_switzerland",
    );

    expect(company).toEqual({
      id: "biogen_switzerland",
      name: "Biogen Switzerland",
      careersUrl:
        "https://biibhr.wd3.myworkdayjobs.com/external?locationCountry=187134fccb084a0ea9b4b95f23890dbe",
      logoSrc: "/company-logos/biogen.svg",
      logoAlt: "Biogen Switzerland logo",
      logoWidth: 69,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("biogen_switzerland-REQ23932")).toBe(
      company,
    );
  });
});

describe("Bristol Myers Squibb Switzerland Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "bms_switzerland",
    );

    expect(company).toEqual({
      id: "bms_switzerland",
      name: "Bristol Myers Squibb Switzerland",
      careersUrl:
        "https://jobs.bms.com/careers?domain=bms.com&start=0&location=Switzerland&pid=137482241804&sort_by=distance&filter_include_remote=1&filter_include_relocation=0",
      logoSrc: "/company-logos/bms.svg",
      logoAlt: "Bristol Myers Squibb Switzerland logo",
      logoWidth: 169,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("bms_switzerland-137482241804")).toBe(
      company,
    );
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

describe("SIX Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "six_group",
    );

    expect(company).toEqual({
      id: "six_group",
      name: "SIX",
      careersUrl:
        "https://jobs.six-group.com/search/?createNewAlert=false&q=&optionsFacetsDD_customfield2=&optionsFacetsDD_country=CH&optionsFacetsDD_customfield1=",
      logoSrc: "/company-logos/six.svg",
      logoAlt: "SIX logo",
      logoWidth: 66,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("six_group-1415188733")).toBe(company);
  });
});

describe("Comerge Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find((item) => item.id === "comerge");

    expect(company).toEqual({
      id: "comerge",
      name: "Comerge",
      careersUrl: "https://www.comerge.net/en/career#",
      logoSrc: "/company-logos/comerge.svg",
      logoAlt: "Comerge logo",
      logoWidth: 110,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("comerge-software-engineer")).toBe(company);
  });
});

describe("Abraxas Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find((item) => item.id === "abraxas");

    expect(company).toEqual({
      id: "abraxas",
      name: "Abraxas Informatik AG",
      careersUrl: "https://www.abraxas.ch/de/karriere/offene-stellen",
      logoSrc: "/company-logos/abraxas.svg",
      logoAlt: "Abraxas Informatik AG logo",
      logoWidth: 29,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("abraxas-9876")).toBe(company);
  });
});

describe("AKROS Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find((item) => item.id === "akros");

    expect(company).toEqual({
      id: "akros",
      name: "AKROS AG",
      careersUrl: "https://www.akros.ch/jobs/",
      logoSrc: "/company-logos/akros.svg",
      logoAlt: "AKROS AG logo",
      logoWidth: 94,
      logoHeight: 24,
    });
    expect(
      getDirectCompanyByJobId("akros-java-software-engineer-fullstack-zurich"),
    ).toBe(company);
  });
});

describe("amétiq Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find((item) => item.id === "ametiq");

    expect(company).toEqual({
      id: "ametiq",
      name: "amétiq ag",
      careersUrl: "https://ametiq.ch/jobs/",
      logoSrc: "/company-logos/ametiq.svg",
      logoAlt: "amétiq ag logo",
      logoWidth: 58,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("ametiq-13617")).toBe(company);
  });
});

describe("BSI Software Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "bsi_software",
    );

    expect(company).toEqual({
      id: "bsi_software",
      name: "BSI Software",
      careersUrl: "https://www.bsi-software.com/en/career/jobs",
      logoSrc: "/company-logos/bsi-software.svg",
      logoAlt: "BSI Software logo",
      logoWidth: 70,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("bsi_software-software-engineer")).toBe(
      company,
    );
  });
});

describe("CM Informatik AG Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find((item) => item.id === "cmi");

    expect(company).toEqual({
      id: "cmi",
      name: "CM Informatik AG",
      careersUrl: "https://cmi.ch/karriere/",
      logoSrc: "/company-logos/cmi.svg",
      logoAlt: "CM Informatik AG logo",
      logoWidth: 24,
      logoHeight: 24,
    });
    expect(
      getDirectCompanyByJobId("cmi-808dbb0a-dde0-d52b-001d-3dcc84d46f46"),
    ).toBe(company);
  });
});

describe("EGELI Informatik AG Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "egeli_informatik",
    );

    expect(company).toEqual({
      id: "egeli_informatik",
      name: "EGELI Informatik AG",
      careersUrl: "https://egeli-informatik.ch/karriere/",
      logoSrc: "/company-logos/egeli-informatik.svg",
      logoAlt: "EGELI Informatik AG logo",
      logoWidth: 87,
      logoHeight: 24,
    });
    expect(
      getDirectCompanyByJobId(
        "egeli_informatik-d77b3af8-f9f7-45b4-9353-d85d64ae37e5",
      ),
    ).toBe(company);
  });
});

describe("emineo AG Direct Company catalog entry", () => {
  it("is selectable and resolves imported vacancy IDs to the official logo", () => {
    const company = directCompanyCatalog.find((item) => item.id === "emineo");

    expect(company).toEqual({
      id: "emineo",
      name: "emineo AG",
      careersUrl: "https://emineo.ch/en/career/open-positions/",
      logoSrc: "/company-logos/emineo.svg",
      logoAlt: "emineo AG logo",
      logoWidth: 24,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("emineo-389")).toBe(company);
  });
});

describe("Hostpoint AG Direct Company catalog entry", () => {
  it("uses the official careers page and local logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "hostpoint",
    );

    expect(company).toEqual({
      id: "hostpoint",
      name: "Hostpoint AG",
      careersUrl: "https://www.hostpoint.ch/en/jobs/",
      logoSrc: "/company-logos/hostpoint.svg",
      logoAlt: "Hostpoint AG logo",
      logoWidth: 126,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("hostpoint-system-engineer-unix")).toBe(
      company,
    );
  });
});

describe("Hürlimann Informatik AG Direct Company catalog entry", () => {
  it("uses the official careers tab and local logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "huerlimann_informatik",
    );

    expect(company).toEqual({
      id: "huerlimann_informatik",
      name: "Hürlimann Informatik AG",
      careersUrl:
        "https://www.hi-ag.ch/unternehmen/karriere#karriere-1266-panel-2",
      logoSrc: "/company-logos/huerlimann-informatik.svg",
      logoAlt: "Hürlimann Informatik AG logo",
      logoWidth: 108,
      logoHeight: 29,
    });
    expect(getDirectCompanyByJobId("huerlimann_informatik-75877")).toBe(
      company,
    );
  });
});

describe("Infosoft Systems AG Direct Company catalog entry", () => {
  it("uses the official careers page and local logo", () => {
    const company = directCompanyCatalog.find((item) => item.id === "infosoft");

    expect(company).toEqual({
      id: "infosoft",
      name: "Infosoft Systems AG",
      careersUrl: "https://infosoft.swiss/karriere/",
      logoSrc: "/company-logos/infosoft.svg",
      logoAlt: "Infosoft Systems AG logo",
      logoWidth: 104,
      logoHeight: 24,
    });
    expect(
      getDirectCompanyByJobId("infosoft-senior-software-engineer-in-net"),
    ).toBe(company);
  });
});

describe("isolutions AG Direct Company catalog entry", () => {
  it("uses the official careers module and local logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "isolutions",
    );

    expect(company).toEqual({
      id: "isolutions",
      name: "isolutions AG",
      careersUrl: "https://www.isolutions.ch/en/career/#module-1396",
      logoSrc: "/company-logos/isolutions.svg",
      logoAlt: "isolutions AG logo",
      logoWidth: 24,
      logoHeight: 25,
    });
    expect(
      getDirectCompanyByJobId(
        "isolutions-junior-technical-consultant-digital-workplace",
      ),
    ).toBe(company);
  });
});

describe("IWF AG Direct Company catalog entry", () => {
  it("uses the official careers page and local logo", () => {
    const company = directCompanyCatalog.find((item) => item.id === "iwf");

    expect(company).toEqual({
      id: "iwf",
      name: "IWF AG",
      careersUrl: "https://www.iwf.ch/web-solutions/jobs",
      logoSrc: "/company-logos/iwf.svg",
      logoAlt: "IWF AG logo",
      logoWidth: 24,
      logoHeight: 25,
    });
    expect(getDirectCompanyByJobId("iwf-agile-tester")).toBe(company);
  });
});

describe("Löwenfels Partner AG Direct Company catalog entry", () => {
  it("uses the official careers page and local logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "loewenfels",
    );

    expect(company).toEqual({
      id: "loewenfels",
      name: "Löwenfels Partner AG",
      careersUrl: "https://www.loewenfels.ch/karriere/",
      logoSrc: "/company-logos/loewenfels.svg",
      logoAlt: "Löwenfels Partner AG logo",
      logoWidth: 132,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("loewenfels-76584")).toBe(company);
  });
});

describe("M&S Software Engineering AG Direct Company catalog entry", () => {
  it("uses the official careers page and local logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "m_s_software_engineering",
    );

    expect(company).toEqual({
      id: "m_s_software_engineering",
      name: "M&S Software Engineering AG",
      careersUrl: "https://www.m-s.ch/karriere/offene-stellen/",
      logoSrc: "/company-logos/m-s-software-engineering.svg",
      logoAlt: "M&S Software Engineering AG logo",
      logoWidth: 110,
      logoHeight: 34,
    });
    expect(
      getDirectCompanyByJobId("m_s_software_engineering-tdpbva0dmo30y"),
    ).toBe(company);
  });
});

describe("Opacc Software AG Direct Company catalog entry", () => {
  it("uses the official jobs site and local logo", () => {
    const company = directCompanyCatalog.find((item) => item.id === "opacc");

    expect(company).toEqual({
      id: "opacc",
      name: "Opacc Software AG",
      careersUrl: "https://jobs.opacc.ch/",
      logoSrc: "/company-logos/opacc.svg",
      logoAlt: "Opacc Software AG logo",
      logoWidth: 84,
      logoHeight: 60,
    });
    expect(
      getDirectCompanyByJobId("opacc-kunden-bedienen-teamleiterin-support"),
    ).toBe(company);
  });
});

describe("Panter AG Direct Company catalog entry", () => {
  it("uses the official careers page and local logo", () => {
    const company = directCompanyCatalog.find((item) => item.id === "panter");

    expect(company).toEqual({
      id: "panter",
      name: "Panter AG",
      careersUrl: "https://www.panter.ch/en/about-us/career/",
      logoSrc: "/company-logos/panter.svg",
      logoAlt: "Panter AG logo",
      logoWidth: 114,
      logoHeight: 30,
    });
    expect(getDirectCompanyByJobId("panter-senior-ai-software-engineer")).toBe(
      company,
    );
  });
});

describe("Digital Architects Zurich GmbH Direct Company catalog entry", () => {
  it("uses the official careers page and local logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "digital_architects_zurich",
    );

    expect(company).toEqual({
      id: "digital_architects_zurich",
      name: "Digital Architects Zurich GmbH",
      careersUrl: "https://digital-architects-zurich.ch/career/",
      logoSrc: "/company-logos/digital-architects-zurich.svg",
      logoAlt: "Digital Architects Zurich GmbH logo",
      logoWidth: 30,
      logoHeight: 30,
    });
    expect(
      getDirectCompanyByJobId("digital_architects_zurich-job-cicd-consultant"),
    ).toBe(company);
  });
});

describe("UMB AG Direct Company catalog entry", () => {
  it("uses the official careers page and local logo", () => {
    const company = directCompanyCatalog.find((item) => item.id === "umb");

    expect(company).toEqual({
      id: "umb",
      name: "UMB AG",
      careersUrl: "https://www.umb.ch/unternehmen/it-jobs-bei-umb",
      logoSrc: "/company-logos/umb.svg",
      logoAlt: "UMB AG logo",
      logoWidth: 95,
      logoHeight: 31,
    });
    expect(getDirectCompanyByJobId("umb-744000143231549")).toBe(company);
  });
});

describe("Webtouch GmbH Direct Company catalog entry", () => {
  it("uses the official careers page and local logo", () => {
    const company = directCompanyCatalog.find((item) => item.id === "webtouch");

    expect(company).toEqual({
      id: "webtouch",
      name: "Webtouch GmbH",
      careersUrl: "https://www.webtouch.ch/karriere",
      logoSrc: "/company-logos/webtouch.svg",
      logoAlt: "Webtouch GmbH logo",
      logoWidth: 131,
      logoHeight: 17,
    });
    expect(getDirectCompanyByJobId("webtouch-call-agent-in-b2b-outbound")).toBe(
      company,
    );
  });
});

describe("Manor AG Direct Company catalog entry", () => {
  it("uses the official careers page and local logo", () => {
    const company = directCompanyCatalog.find((item) => item.id === "manor");

    expect(company).toEqual({
      id: "manor",
      name: "Manor AG",
      careersUrl: "https://careers.manor.ch/de/offene-stellen/offene-stellen",
      logoSrc: "/company-logos/manor.svg",
      logoAlt: "Manor AG logo",
      logoWidth: 120,
      logoHeight: 40,
    });
    expect(getDirectCompanyByJobId("manor-4041835")).toBe(company);
  });
});

describe("Salt Mobile SA Direct Company catalog entry", () => {
  it("uses the official JobCloud-hosted careers page and local logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "salt_mobile",
    );

    expect(company).toEqual({
      id: "salt_mobile",
      name: "Salt Mobile SA",
      careersUrl:
        "https://company.jobcloud.ch/de/job-list/1772460841133x163767963229093900?embedded=yes",
      logoSrc: "/company-logos/salt-mobile.svg",
      logoAlt: "Salt Mobile SA logo",
      logoWidth: 100,
      logoHeight: 40,
    });
    expect(
      getDirectCompanyByJobId(
        "salt_mobile-b6bb546f-f060-4a80-98bb-cc5d31f82a54",
      ),
    ).toBe(company);
  });
});

describe("V-ZUG AG Direct Company catalog entry", () => {
  it("uses the official careers page and local logo", () => {
    const company = directCompanyCatalog.find((item) => item.id === "vzug");

    expect(company).toEqual({
      id: "vzug",
      name: "V-ZUG AG",
      careersUrl: "https://www.vzug.com/ch/de/jobs",
      logoSrc: "/company-logos/vzug.svg",
      logoAlt: "V-ZUG AG logo",
      logoWidth: 36,
      logoHeight: 36,
    });
    expect(
      getDirectCompanyByJobId("vzug-69b70fad-c7ef-4a6a-932f-db7a00ff345d"),
    ).toBe(company);
  });
});

describe("Lindt & Sprüngli (Schweiz) AG Direct Company catalog entry", () => {
  it("uses the official Swiss hiring-company facet and local logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "lindt_spruengli_switzerland",
    );

    expect(company).toEqual({
      id: "lindt_spruengli_switzerland",
      name: "Lindt & Sprüngli (Schweiz) AG",
      careersUrl:
        "https://lindtspruengli.wd103.myworkdayjobs.com/LindtSpruengliGroupCareers?hiringCompany=6ef234644ca31000c2704c6d47960000",
      logoSrc: "/company-logos/lindt-spruengli.svg",
      logoAlt: "Lindt & Sprüngli (Schweiz) AG logo",
      logoWidth: 102,
      logoHeight: 30,
    });
    expect(
      getDirectCompanyByJobId("lindt_spruengli_switzerland-jr102591"),
    ).toBe(company);
  });
});

describe("PwC Switzerland Direct Company catalog entry", () => {
  it("uses the official careers page and local logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "pwc_switzerland",
    );

    expect(company).toEqual({
      id: "pwc_switzerland",
      name: "PwC Switzerland",
      careersUrl: "https://www.pwc.ch/en/careers-with-pwc/open-positions.html",
      logoSrc: "/company-logos/pwc-switzerland.svg",
      logoAlt: "PwC Switzerland logo",
      logoWidth: 53,
      logoHeight: 40,
    });
    expect(
      getDirectCompanyByJobId(
        "pwc_switzerland-00000000-0000-4000-8000-000000000001",
      ),
    ).toBe(company);
  });
});

describe("TX Group AG Direct Company catalog entry", () => {
  it("uses the official Teamtailor careers page and local logo", () => {
    const company = directCompanyCatalog.find((item) => item.id === "tx_group");

    expect(company).toEqual({
      id: "tx_group",
      name: "TX Group AG",
      careersUrl: "https://jobs.tx.group/jobs",
      logoSrc: "/company-logos/tx-group.svg",
      logoAlt: "TX Group AG logo",
      logoWidth: 112,
      logoHeight: 32,
    });
    expect(getDirectCompanyByJobId("tx_group-8172175")).toBe(company);
  });
});

describe("Artificialy SA Direct Company catalog entry", () => {
  it("uses the official careers page and local logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "artificialy",
    );

    expect(company).toEqual({
      id: "artificialy",
      name: "Artificialy SA",
      careersUrl: "https://www.artificialy.com/career",
      logoSrc: "/company-logos/artificialy.svg",
      logoAlt: "Artificialy SA logo",
      logoWidth: 38,
      logoHeight: 32,
    });
    expect(getDirectCompanyByJobId("artificialy-4440007645")).toBe(company);
  });
});

describe("cyon AG Direct Company catalog entry", () => {
  it("uses the official careers page and local logo", () => {
    const company = directCompanyCatalog.find((item) => item.id === "cyon");

    expect(company).toEqual({
      id: "cyon",
      name: "cyon AG",
      careersUrl: "https://www.cyon.ch/ueber-cyon/jobs",
      logoSrc: "/company-logos/cyon.svg",
      logoAlt: "cyon AG logo",
      logoWidth: 107,
      logoHeight: 40,
    });
    expect(
      getDirectCompanyByJobId("cyon-d46bed06fa68418c88ef3d14927e138a"),
    ).toBe(company);
  });
});

describe("Schindler Group Direct Company catalog entry", () => {
  it("uses the official Swiss SuccessFactors facet and local logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "schindler_switzerland",
    );

    expect(company).toEqual({
      id: "schindler_switzerland",
      name: "Schindler Group",
      careersUrl:
        "https://job.schindler.com/search/?createNewAlert=false&q=&locationsearch=&optionsFacetsDD_country=CH",
      logoSrc: "/company-logos/schindler.svg",
      logoAlt: "Schindler Group logo",
      logoWidth: 40,
      logoHeight: 40,
    });
    expect(getDirectCompanyByJobId("schindler_switzerland-1416306233")).toBe(
      company,
    );
  });
});

describe("Sonova Group Direct Company catalog entry", () => {
  it("uses the official Swiss careers facet and local logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "sonova_switzerland",
    );

    expect(company).toEqual({
      id: "sonova_switzerland",
      name: "Sonova Group",
      careersUrl:
        "https://www.sonova.com/careers/?query-1-job-country=switzerland",
      logoSrc: "/company-logos/sonova.svg",
      logoAlt: "Sonova Group logo",
      logoWidth: 40,
      logoHeight: 40,
    });
    expect(getDirectCompanyByJobId("sonova_switzerland-164409")).toBe(company);
  });
});

describe("Elektro-Material AG Direct Company catalog entry", () => {
  it("uses the official open-positions page and local logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "elektro_material",
    );

    expect(company).toEqual({
      id: "elektro_material",
      name: "Elektro-Material AG",
      careersUrl:
        "https://elektro-material.ch/de/cms/seite/offene-stellen-t33143s226453a4614994",
      logoSrc: "/company-logos/elektro-material.svg",
      logoAlt: "Elektro-Material AG logo",
      logoWidth: 49,
      logoHeight: 40,
    });
    expect(getDirectCompanyByJobId("elektro_material-744000139266729")).toBe(
      company,
    );
  });
});

describe("CSL Switzerland Direct Company catalog entry", () => {
  it("uses the official Swiss jobs filter and local logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "csl_switzerland",
    );

    expect(company).toEqual({
      id: "csl_switzerland",
      name: "CSL Switzerland",
      careersUrl:
        "https://jobs.csl.com/en/jobs?filterrific%5Bwith_location3%5D=switzerland&filterrific%5Bsorted_by%5D=newest",
      logoSrc: "/company-logos/csl.svg",
      logoAlt: "CSL logo",
      logoWidth: 53,
      logoHeight: 40,
    });
    expect(getDirectCompanyByJobId("csl_switzerland-283348")).toBe(company);
  });
});

describe("Lonza Switzerland Direct Company catalog entry", () => {
  it("uses the official Swiss-filterable catalog and local logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "lonza_switzerland",
    );

    expect(company).toEqual({
      id: "lonza_switzerland",
      name: "Lonza Switzerland",
      careersUrl: "https://www.lonza.com/careers/job-search",
      logoSrc: "/company-logos/lonza.svg",
      logoAlt: "Lonza Switzerland logo",
      logoWidth: 155,
      logoHeight: 28,
    });
    expect(getDirectCompanyByJobId("lonza_switzerland-R78588")).toBe(company);
  });
});

describe("Nestlé Switzerland Direct Company catalog entry", () => {
  it("uses the official Swiss jobs filter and local logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "nestle_switzerland",
    );

    expect(company).toEqual({
      id: "nestle_switzerland",
      name: "Nestlé Switzerland",
      careersUrl:
        "https://www.nestle.com/jobs/search-jobs?keyword=&country=CH&location=&career_area=All",
      logoSrc: "/company-logos/nestle.svg",
      logoAlt: "Nestlé Switzerland logo",
      logoWidth: 154,
      logoHeight: 40,
    });
    expect(getDirectCompanyByJobId("nestle_switzerland-1386110633")).toBe(
      company,
    );
  });
});

describe("AFRY Switzerland Direct Company catalog entry", () => {
  it("uses the official Swiss jobs page and local logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "afry_switzerland",
    );

    expect(company).toEqual({
      id: "afry_switzerland",
      name: "AFRY Switzerland",
      careersUrl: "https://afry.com/de-ch/karriere/verfugbare-stellen",
      logoSrc: "/company-logos/afry.svg",
      logoAlt: "AFRY Switzerland logo",
      logoWidth: 174,
      logoHeight: 40,
    });
    expect(getDirectCompanyByJobId("afry_switzerland-744000143442729")).toBe(
      company,
    );
  });
});

describe("Digital Realty Switzerland Direct Company catalog entry", () => {
  it("uses the official Swiss jobs page and local logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "digital_realty_switzerland",
    );

    expect(company).toEqual({
      id: "digital_realty_switzerland",
      name: "Digital Realty Switzerland",
      careersUrl:
        "https://hdep.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX/jobs?location=Switzerland&locationId=300000000361301&locationLevel=country&mode=job-location",
      logoSrc: "/company-logos/digital-realty.svg",
      logoAlt: "Digital Realty Switzerland logo",
      logoWidth: 114,
      logoHeight: 40,
    });
    expect(getDirectCompanyByJobId("digital_realty_switzerland-8361")).toBe(
      company,
    );
  });
});

describe("Equans Switzerland Direct Company catalog entry", () => {
  it("uses the official Swiss jobs filter and local logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "equans_switzerland",
    );

    expect(company).toEqual({
      id: "equans_switzerland",
      name: "Equans Switzerland",
      careersUrl:
        "https://www.equans.com/join-us?jobs_offer%5BrefinementList%5D%5Bcountry_en%5D%5B0%5D=Switzerland",
      logoSrc: "/company-logos/equans.svg",
      logoAlt: "Equans Switzerland logo",
      logoWidth: 134,
      logoHeight: 40,
    });
    expect(getDirectCompanyByJobId("equans_switzerland-100001144")).toBe(
      company,
    );
  });
});

describe("Bison Group Direct Company catalog entry", () => {
  it("uses the official jobs page and local logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "bison_group",
    );

    expect(company).toEqual({
      id: "bison_group",
      name: "Bison Group",
      careersUrl:
        "https://www.bison-group.com/karriere/offene-stellen/",
      logoSrc: "/company-logos/bison-group.svg",
      logoAlt: "Bison Group logo",
      logoWidth: 40,
      logoHeight: 40,
    });
    expect(getDirectCompanyByJobId("bison_group-10143471")).toBe(company);
  });
});

describe("PRODYNA Switzerland Direct Company catalog entry", () => {
  it("uses the official Zurich jobs filter and local logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "prodyna_switzerland",
    );

    expect(company).toEqual({
      id: "prodyna_switzerland",
      name: "PRODYNA Switzerland",
      careersUrl: "https://www.prodyna.com/jobs?location=Zurich",
      logoSrc: "/company-logos/prodyna.svg",
      logoAlt: "PRODYNA Switzerland logo",
      logoWidth: 141,
      logoHeight: 24,
    });
    expect(
      getDirectCompanyByJobId("prodyna_switzerland-zurich-full-stack"),
    ).toBe(company);
  });
});

describe("cross-ING Switzerland Direct Company catalog entry", () => {
  it("uses the official Swiss jobs filter and local logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "crossing_switzerland",
    );

    expect(company).toEqual({
      id: "crossing_switzerland",
      name: "cross-ING Switzerland",
      careersUrl:
        "https://crossing.recruitee.com/?jobs-c88dea0d%5Bcountry%5D%5B%5D=CH",
      logoSrc: "/company-logos/crossing.svg",
      logoAlt: "cross-ING Switzerland logo",
      logoWidth: 137,
      logoHeight: 36,
    });
    expect(getDirectCompanyByJobId("crossing_switzerland-2652347")).toBe(
      company,
    );
  });
});

describe("NetApp Switzerland Direct Company catalog entry", () => {
  it("uses the official Swiss jobs filter and local logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "netapp_switzerland",
    );

    expect(company).toEqual({
      id: "netapp_switzerland",
      name: "NetApp Switzerland",
      careersUrl:
        "https://careers.netapp.com/location/switzerland-jobs/27600/2658434/2",
      logoSrc: "/company-logos/netapp.svg",
      logoAlt: "NetApp Switzerland logo",
      logoWidth: 122,
      logoHeight: 22,
    });
    expect(getDirectCompanyByJobId("netapp_switzerland-98797033984")).toBe(
      company,
    );
  });
});

describe("Sharp Switzerland Direct Company catalog entry", () => {
  it("uses the official Swiss careers page and local logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "sharp_switzerland",
    );

    expect(company).toEqual({
      id: "sharp_switzerland",
      name: "Sharp Switzerland",
      careersUrl: "https://www.sharp.ch/de/jobs-bei-sharp",
      logoSrc: "/company-logos/sharp.svg",
      logoAlt: "Sharp Switzerland logo",
      logoWidth: 152,
      logoHeight: 22,
    });
    expect(
      getDirectCompanyByJobId(
        "sharp_switzerland-account-manager-mwd-region-romandie",
      ),
    ).toBe(company);
  });
});

describe("Unisys Switzerland Direct Company catalog entry", () => {
  it("uses the official Workday country filter and local logo", () => {
    const company = directCompanyCatalog.find(
      (item) => item.id === "unisys_switzerland",
    );

    expect(company).toEqual({
      id: "unisys_switzerland",
      name: "Unisys Switzerland",
      careersUrl:
        "https://unisys.wd5.myworkdayjobs.com/External?locationCountry=187134fccb084a0ea9b4b95f23890dbe",
      logoSrc: "/company-logos/unisys.svg",
      logoAlt: "Unisys Switzerland logo",
      logoWidth: 26,
      logoHeight: 24,
    });
    expect(getDirectCompanyByJobId("unisys_switzerland-REQ573110")).toBe(
      company,
    );
  });
});
