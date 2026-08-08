import { getTargetGeometry } from "@/lib/target-geometry";
import type { ActivityShot, TargetKind } from "@/lib/types";

interface PrintTargetProps {
  shots: ActivityShot[];
  targetKind: TargetKind;
  zoom: number;
}

export function PrintTarget({ shots, targetKind, zoom }: PrintTargetProps) {
  const geometry = getTargetGeometry(targetKind);
  const scale = geometry.baseScale * zoom;

  return (
    <svg
      aria-label={`${targetKind} target with ${shots.length} plotted shots`}
      className="print-target-svg"
      role="img"
      viewBox="0 0 200 200"
    >
      <rect fill="#fff" height="200" width="200" />
      <g transform={`translate(100 100) scale(${scale}) translate(-100 -100)`}>
        {geometry.rings.map((ring, index) => (
          <circle
            cx="100"
            cy="100"
            fill={ring.black ? "#000" : "#fff"}
            key={`${ring.radius}-${index}`}
            r={ring.radius}
            stroke={ring.black ? "#fff" : "#000"}
            strokeWidth="1"
          />
        ))}

        {shots.map((shot, index) => {
          const label = String(index + 1);
          return (
            <g
              key={shot.shotKey}
              transform={`translate(${100 + shot.xMm * 4} ${100 - shot.yMm * 4})`}
            >
              <circle
                fill="#fff"
                r={geometry.shotRadius + 2}
                stroke="#fff"
                strokeWidth="2"
              />
              <circle
                fill="#fff"
                r={geometry.shotRadius}
                stroke="#000"
                strokeWidth="1.4"
              />
              <text
                dominantBaseline="central"
                fill="#000"
                fontSize={geometry.shotRadius * 0.92}
                fontWeight="700"
                textAnchor="middle"
              >
                {label}
              </text>
            </g>
          );
        })}
      </g>
      <line className="print-target-crosshair" x1="96" x2="104" y1="100" y2="100" />
      <line className="print-target-crosshair" x1="100" x2="100" y1="96" y2="104" />
    </svg>
  );
}
