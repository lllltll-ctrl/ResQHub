import { clsx } from "clsx";

export function ScoreRing({
  score,
  size = 60,
  thickness = 6,
}: {
  score: number;
  size?: number;
  thickness?: number;
}) {
  const r = (size - thickness) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, score));
  const offset = c - (pct / 100) * c;

  // Ті самі пороги/кольори, що й у StatusPill (globals.css chip-*)
  const color =
    pct >= 70 ? "#4ae176" : pct >= 40 ? "#df7412" : "#ffb4ab";

  return (
    <svg width={size} height={size} className="block">
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        stroke="#243352"
        strokeWidth={thickness}
        fill="none"
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        stroke={color}
        strokeWidth={thickness}
        fill="none"
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={offset}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: "stroke-dashoffset 0.6s ease" }}
      />
      <text
        x="50%"
        y="50%"
        textAnchor="middle"
        dominantBaseline="central"
        className={clsx("font-mono font-semibold fill-text")}
        fontSize={size * 0.26}
      >
        {Math.round(pct)}
      </text>
    </svg>
  );
}