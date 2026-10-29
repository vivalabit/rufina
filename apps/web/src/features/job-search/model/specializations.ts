import type { DirectCompanyDirection } from "@/features/job-search/model/types";

export const directCompanySpecializationOptions: Record<
  DirectCompanyDirection,
  readonly string[]
> = {
  information_technology: [
    "Backend",
    "Frontend",
    "Full-stack",
    "Mobile",
    "QA",
    "DevOps",
    "Data Engineering",
    "Data Science",
    "Cybersecurity",
    "IT Support",
    "System Administration",
  ],
  marketing: [
    "Digital Marketing",
    "Content Marketing",
    "SEO",
    "Brand Management",
    "Product Marketing",
  ],
  sales: [
    "Account Management",
    "Business Development",
    "Inside Sales",
    "Sales Engineering",
  ],
  finance_accounting: [
    "Accounting",
    "Controlling",
    "Financial Analysis",
    "Audit",
    "Tax",
  ],
  design: ["UX Design", "UI Design", "Product Design", "Graphic Design"],
  human_resources: [
    "Recruiting",
    "HR Operations",
    "HR Business Partner",
    "Learning & Development",
  ],
  operations: [
    "Project Management",
    "Supply Chain",
    "Logistics",
    "Procurement",
  ],
  customer_support: [
    "Customer Support",
    "Technical Support",
    "Customer Success",
  ],
  engineering: [
    "Mechanical Engineering",
    "Electrical Engineering",
    "Civil Engineering",
    "Automation",
    "Embedded Systems",
  ],
  healthcare: [
    "Nursing",
    "Medicine",
    "Physiotherapy",
    "Pharmacy",
    "Medical Laboratory",
  ],
  legal: ["Legal Counsel", "Compliance", "Paralegal", "Data Protection"],
  all: [],
};
