import type { Job } from "@/shared/types/job";

export const demoJobs: Job[] = [
  {
    id: "stripe-senior-product-designer",
    company: "Stripe",
    title: "Senior Product Designer",
    location: "Remote",
    type: "Full-time",
    salary: "$120k - $160k",
    posted: "2h ago",
    experience: "5+ years",
    department: "Product Design",
    match: 92,
    logo: "stripe",
    overview:
      "We're looking for a Senior Product Designer to join our team and help design the future of online payments. You'll work on complex problems that impact millions of businesses worldwide.",
    responsibilities: [
      "Lead design projects from concept to execution",
      "Collaborate with cross-functional teams",
      "Design user-centered solutions for complex problems",
      "Mentor junior designers",
    ],
    requirements: [
      "5+ years of product design experience",
      "Strong portfolio demonstrating design thinking",
      "Experience with design systems",
      "Excellent communication skills",
    ],
    skills: ["Figma", "Sketch", "Design Systems", "User Research", "Prototyping"],
    salaryAverage: "$140k",
    salaryMin: "$120k",
    salaryMax: "$160k",
    recommendations: [],
    companyInfo:
      "Stripe builds financial infrastructure for internet businesses, with design teams focused on developer tools, dashboards, and payment experiences.",
    reviews: [
      "Design quality bar is high and feedback cycles are direct.",
      "Strong product culture with close engineering collaboration.",
    ],
    similarJobs: [
      "Staff Product Designer at Square",
      "Design Systems Lead at Ramp",
      "Senior UX Designer at Shopify",
    ],
  },
  {
    id: "figma-product-design-lead",
    company: "Figma",
    title: "Product Design Lead",
    location: "Remote",
    type: "Full-time",
    salary: "$130k - $170k",
    posted: "5h ago",
    experience: "6+ years",
    department: "Editor Experience",
    match: 89,
    logo: "figma",
    overview:
      "Figma is hiring a Product Design Lead to shape collaborative creation workflows for designers, engineers, and product teams. This role owns strategy, craft, and team rituals for high-impact editor surfaces.",
    responsibilities: [
      "Define the product design direction for core collaboration flows",
      "Partner with research, product, and engineering leads",
      "Prototype new interaction models",
      "Coach designers through critiques and launches",
    ],
    requirements: [
      "6+ years designing creative or productivity tools",
      "Experience leading ambiguous product initiatives",
      "Strong systems thinking and interaction design craft",
      "Comfort presenting design rationale to leadership",
    ],
    skills: ["Figma", "Prototyping", "Design Strategy", "Research", "Collaboration"],
    salaryAverage: "$150k",
    salaryMin: "$130k",
    salaryMax: "$170k",
    recommendations: [],
    companyInfo:
      "Figma creates collaborative design and product development software used by teams to ideate, design, prototype, and ship together.",
    reviews: [
      "Fast-moving product teams with thoughtful design critique.",
      "Strong remote culture and high ownership expectations.",
    ],
    similarJobs: [
      "Principal Product Designer at Miro",
      "Design Lead at Linear",
      "Senior Product Designer at Webflow",
    ],
  },
];
