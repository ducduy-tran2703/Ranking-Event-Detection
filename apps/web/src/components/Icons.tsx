// Biểu tượng nét (stroke) dùng chung, vẽ theo bản thiết kế. Luôn aria-hidden: nút chỉ có icon phải tự có aria-label.
type P = { size?: number; className?: string };
const base = (size = 18) => ({
  width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2,
  strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true, focusable: false,
});

export const IconTrend = ({ size = 18, className }: P) => (
  <svg {...base(size)} strokeWidth={2.4} className={className}>
    <polyline points="3 17 9 11 13 15 21 7" /><polyline points="15 7 21 7 21 13" />
  </svg>
);
export const IconSearch = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}><circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg>
);
export const IconUser = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
  </svg>
);
export const IconMenu = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}><line x1="4" y1="7" x2="20" y2="7" /><line x1="4" y1="12" x2="20" y2="12" /><line x1="4" y1="17" x2="20" y2="17" /></svg>
);
export const IconClose = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}><line x1="6" y1="6" x2="18" y2="18" /><line x1="18" y1="6" x2="6" y2="18" /></svg>
);
export const IconBell = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 0 1-3.46 0" />
  </svg>
);
export const IconBookmark = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" /></svg>
);
export const IconLink = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
    <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
  </svg>
);
export const IconFlag = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" /><line x1="4" y1="22" x2="4" y2="15" />
  </svg>
);
export const IconChevronLeft = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}><path d="M15 18l-6-6 6-6" /></svg>
);
export const IconChevronRight = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}><path d="M9 18l6-6-6-6" /></svg>
);
export const IconExternal = ({ size = 15, className }: P) => (
  <svg {...base(size)} className={className}><path d="M7 17 17 7" /><path d="M8 7h9v9" /></svg>
);
export const IconArrowLeft = ({ size = 16, className }: P) => (
  <svg {...base(size)} className={className}><path d="M19 12H5" /><path d="m12 19-7-7 7-7" /></svg>
);
export const IconCheck = ({ size = 16, className }: P) => (
  <svg {...base(size)} className={className}><path d="M20 6 9 17l-5-5" /></svg>
);
export const IconMail = ({ size = 22, className }: P) => (
  <svg {...base(size)} className={className}><rect x="3" y="5" width="18" height="14" /><path d="m3 7 9 6 9-6" /></svg>
);
export const IconAlert = ({ size = 16, className }: P) => (
  <svg {...base(size)} className={className}><path d="M12 3 2 20h20L12 3z" /><path d="M12 10v4" /><path d="M12 17h.01" /></svg>
);
export const IconSpinner = ({ size = 16, className }: P) => (
  <svg {...base(size)} strokeWidth={2.5} className={className}><path d="M21 12a9 9 0 1 1-6.2-8.56" /></svg>
);
