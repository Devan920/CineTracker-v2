export function HeroSpotlightSkeleton() {
  return (
    <div
      aria-hidden="true"
      className="relative overflow-hidden rounded-2xl border border-white/[0.08] bg-[#12151E] p-4 sm:rounded-3xl sm:p-8"
    >
      <div className="grid gap-4 sm:gap-6 lg:grid-cols-[auto_1fr_auto] lg:items-center">
        <div className="ct-shimmer-skeleton mx-auto aspect-[2/3] w-28 rounded-2xl border border-white/[0.08] sm:mx-0 sm:w-44" />

        <div className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <div className="ct-shimmer-skeleton h-5 w-24 rounded-full bg-[#191E2B]" />
            <div className="ct-shimmer-skeleton h-5 w-20 rounded-full bg-[#191E2B]" />
            <div className="ct-shimmer-skeleton h-5 w-16 rounded-full bg-[#191E2B]" />
          </div>
          <div className="ct-shimmer-skeleton h-9 w-3/4 rounded-xl bg-[#191E2B] sm:h-10" />
          <div className="ct-shimmer-skeleton h-4 w-1/2 rounded-lg bg-[#191E2B]" />
          <div className="ct-shimmer-skeleton h-8 w-64 rounded-xl bg-[#191E2B]" />
          <div className="flex flex-wrap gap-2 pt-1">
            <div className="ct-shimmer-skeleton h-10 w-36 rounded-xl bg-[#191E2B]" />
            <div className="ct-shimmer-skeleton h-10 w-32 rounded-xl bg-[#191E2B]" />
            <div className="ct-shimmer-skeleton h-10 w-24 rounded-xl bg-[#191E2B]" />
          </div>
        </div>

        <div className="space-y-3 rounded-2xl border border-white/[0.08] bg-[#090A0F]/80 p-4 sm:min-w-[310px] sm:p-5">
          <div className="ct-shimmer-skeleton h-4 w-32 rounded bg-[#191E2B]" />
          <div className="ct-shimmer-skeleton h-10 w-44 rounded-lg bg-[#191E2B]" />
          <div className="grid grid-cols-3 gap-2 pt-2">
            <div className="ct-shimmer-skeleton h-10 rounded-lg bg-[#191E2B]" />
            <div className="ct-shimmer-skeleton h-10 rounded-lg bg-[#191E2B]" />
            <div className="ct-shimmer-skeleton h-10 rounded-lg bg-[#191E2B]" />
          </div>
        </div>
      </div>
    </div>
  );
}

export function MovieCardGridSkeleton({ count = 8 }: { count?: number }) {
  return (
    <div
      aria-hidden="true"
      className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-4 lg:gap-5"
    >
      {Array.from({ length: count }).map((_, idx) => (
        <div
          key={idx}
          className="overflow-hidden rounded-2xl border border-white/[0.08] bg-[#12151E]"
        >
          <div className="ct-shimmer-skeleton aspect-[2/3] w-full" />
          <div className="space-y-2.5 p-2.5 sm:p-4">
            <div className="ct-shimmer-skeleton h-4 w-4/5 rounded bg-[#191E2B]" />
            <div className="ct-shimmer-skeleton h-3 w-1/2 rounded bg-[#191E2B]" />
            <div className="grid grid-cols-2 gap-1.5 pt-1">
              <div className="ct-shimmer-skeleton h-10 rounded-xl bg-[#191E2B]" />
              <div className="ct-shimmer-skeleton h-10 rounded-xl bg-[#191E2B]" />
            </div>
            <div className="hidden h-2 rounded-full bg-[#191E2B] sm:block" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function RechartsSectionSkeleton() {
  return (
    <div aria-hidden="true" className="grid gap-5 lg:grid-cols-3">
      <div className="rounded-2xl border border-white/[0.08] bg-[#12151E] p-4 sm:p-5 lg:col-span-2">
        <div className="mb-4 flex items-center justify-between">
          <div className="space-y-1.5">
            <div className="ct-shimmer-skeleton h-4 w-48 rounded bg-[#191E2B]" />
            <div className="ct-shimmer-skeleton h-3 w-32 rounded bg-[#191E2B]" />
          </div>
          <div className="ct-shimmer-skeleton h-8 w-36 rounded-xl bg-[#191E2B]" />
        </div>
        <div className="flex h-[240px] items-end gap-2.5 rounded-xl border border-white/[0.06] bg-[#090A0F]/60 px-4 pb-4 pt-8">
          {[42, 74, 58, 92, 65, 48, 84, 53, 39, 68].map((h, i) => (
            <div
              key={i}
              style={{ height: `${h}%` }}
              className="ct-shimmer-skeleton flex-1 rounded-t-md bg-[#191E2B]"
            />
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-5">
        <div className="rounded-2xl border border-white/[0.08] bg-[#12151E] p-4 sm:p-5">
          <div className="ct-shimmer-skeleton h-4 w-44 rounded bg-[#191E2B]" />
          <div className="mt-4 flex items-center gap-4">
            <div className="ct-shimmer-skeleton h-28 w-28 shrink-0 rounded-full bg-[#191E2B]" />
            <div className="flex-1 space-y-2.5">
              <div className="ct-shimmer-skeleton h-4 w-full rounded bg-[#191E2B]" />
              <div className="ct-shimmer-skeleton h-4 w-4/5 rounded bg-[#191E2B]" />
            </div>
          </div>
        </div>
        <div className="rounded-2xl border border-white/[0.08] bg-[#12151E] p-4 sm:p-5">
          <div className="ct-shimmer-skeleton h-4 w-36 rounded bg-[#191E2B]" />
          <div className="ct-shimmer-skeleton mt-4 h-3 w-full rounded-full bg-[#191E2B]" />
        </div>
      </div>
    </div>
  );
}

export function MovieDetailSkeleton() {
  return (
    <div aria-hidden="true" className="space-y-6 py-2">
      <div className="rounded-2xl border border-white/[0.08] bg-[#12151E] p-5 sm:p-7">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-end">
          <div className="ct-shimmer-skeleton mx-auto aspect-[2/3] w-32 shrink-0 rounded-2xl bg-[#191E2B] sm:mx-0 sm:w-40" />
          <div className="flex-1 space-y-3">
            <div className="flex gap-2">
              <div className="ct-shimmer-skeleton h-5 w-20 rounded-full bg-[#191E2B]" />
              <div className="ct-shimmer-skeleton h-5 w-24 rounded-full bg-[#191E2B]" />
            </div>
            <div className="ct-shimmer-skeleton h-8 w-2/3 rounded-xl bg-[#191E2B]" />
            <div className="ct-shimmer-skeleton h-4 w-1/2 rounded bg-[#191E2B]" />
            <div className="ct-shimmer-skeleton h-10 w-36 rounded-xl bg-[#191E2B]" />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 xl:grid-cols-7">
        {Array.from({ length: 7 }).map((_, i) => (
          <div
            key={i}
            className="ct-shimmer-skeleton h-16 rounded-2xl border border-white/[0.08]"
          />
        ))}
      </div>

      <RechartsSectionSkeleton />
    </div>
  );
}

export function ComparisonSkeleton() {
  return (
    <div aria-hidden="true" className="space-y-6">
      <div className="rounded-2xl border border-white/[0.08] bg-[#12151E] p-5">
        <div className="ct-shimmer-skeleton h-6 w-64 rounded bg-[#191E2B]" />
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div className="ct-shimmer-skeleton h-24 rounded-xl bg-[#191E2B]" />
          <div className="ct-shimmer-skeleton h-24 rounded-xl bg-[#191E2B]" />
        </div>
      </div>
      <div className="rounded-2xl border border-white/[0.08] bg-[#12151E] p-5">
        <div className="ct-shimmer-skeleton h-[240px] w-full rounded-xl bg-[#191E2B]" />
      </div>
    </div>
  );
}

export function AdminSkeleton() {
  return (
    <div aria-hidden="true" className="space-y-5">
      <div className="ct-shimmer-skeleton h-24 rounded-2xl border border-white/[0.08]" />
      <div className="ct-shimmer-skeleton h-32 rounded-2xl border border-white/[0.08]" />
      <div className="ct-shimmer-skeleton h-80 rounded-2xl border border-white/[0.08]" />
    </div>
  );
}
