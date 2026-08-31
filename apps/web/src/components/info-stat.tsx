type InfoStatProps = {
  label: string;
  value: string;
  title?: string;
};

export function InfoStat({ label, value, title }: InfoStatProps) {
  return (
    <div className="rounded-md border border-border bg-[#fff8f1] p-2.5 2xl:p-3" title={title}>
      <p className="text-xs font-semibold uppercase text-muted">{label}</p>
      <p className="mt-1.5 text-[13px] font-bold text-foreground 2xl:mt-2 2xl:text-sm">{value}</p>
    </div>
  );
}
