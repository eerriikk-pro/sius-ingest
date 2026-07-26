"use client";

import { useState } from "react";

import type { ActivityShot, TargetKind } from "@/lib/types";

interface ShotTargetProps {
  shots: ActivityShot[];
  targetKind: TargetKind;
  hoveredShotKey: string | null;
  selectedShotKeys: Set<string>;
}

const RIFLE_RINGS = [
  { radius: 91, fill: "#fffdf5", stroke: "#c9c2ad" },
  { radius: 81, fill: "#fffdf5", stroke: "#c9c2ad" },
  { radius: 71, fill: "#fffdf5", stroke: "#c9c2ad" },
  { radius: 61, fill: "#20221f", stroke: "#fffdf5" },
  { radius: 51, fill: "#20221f", stroke: "#fffdf5" },
  { radius: 41, fill: "#20221f", stroke: "#fffdf5" },
  { radius: 31, fill: "#20221f", stroke: "#fffdf5" },
  { radius: 21, fill: "#20221f", stroke: "#fffdf5" },
  { radius: 11, fill: "#20221f", stroke: "#fffdf5" },
  { radius: 1, fill: "#fffdf5", stroke: "#fffdf5" },
] as const;

const PISTOL_RINGS = [
  { radius: 311, fill: "#fffdf5", stroke: "#c9c2ad" },
  { radius: 279, fill: "#fffdf5", stroke: "#c9c2ad" },
  { radius: 247, fill: "#fffdf5", stroke: "#c9c2ad" },
  { radius: 215, fill: "#fffdf5", stroke: "#c9c2ad" },
  { radius: 183, fill: "#fffdf5", stroke: "#c9c2ad" },
  { radius: 151, fill: "#fffdf5", stroke: "#c9c2ad" },
  { radius: 119, fill: "#20221f", stroke: "#fffdf5" },
  { radius: 87, fill: "#20221f", stroke: "#fffdf5" },
  { radius: 55, fill: "#20221f", stroke: "#fffdf5" },
  { radius: 23, fill: "#20221f", stroke: "#fffdf5" },
  { radius: 10, fill: "#fffdf5", stroke: "#fffdf5" },
] as const;

export function ShotTarget({
  shots,
  targetKind,
  hoveredShotKey,
  selectedShotKeys,
}: ShotTargetProps) {
  const [zoom, setZoom] = useState(1);
  const isPistol = targetKind === "air-pistol";
  const baseScale = isPistol ? 0.3 : 1;
  const scale = baseScale * zoom;
  const rings = isPistol ? PISTOL_RINGS : RIFLE_RINGS;
  const shotRadius = isPistol ? 18 : 8;
  const hasSelection = selectedShotKeys.size > 0;

  return (
    <div className="target-panel">
      <div className="target-toolbar">
        <span>{isPistol ? "10 m pistol" : "10 m rifle"}</span>
        <div className="zoom-controls" aria-label="Target zoom controls">
          <button
            aria-label="Zoom out"
            disabled={zoom <= 0.75}
            onClick={() => setZoom((current) => Math.max(0.75, current - 0.25))}
            type="button"
          >
            −
          </button>
          <output>{Math.round(zoom * 100)}%</output>
          <button
            aria-label="Zoom in"
            disabled={zoom >= 2.25}
            onClick={() => setZoom((current) => Math.min(2.25, current + 0.25))}
            type="button"
          >
            +
          </button>
        </div>
      </div>

      <svg
        aria-label={`${targetKind} target with ${shots.length} plotted shots`}
        className="shot-target"
        role="img"
        viewBox="0 0 200 200"
      >
        <rect fill="#f4ead0" height="200" width="200" />
        <g transform={`translate(100 100) scale(${scale}) translate(-100 -100)`}>
          {rings.map((ring, index) => (
            <circle
              cx="100"
              cy="100"
              fill={ring.fill}
              key={`${ring.radius}-${index}`}
              r={ring.radius}
              stroke={ring.stroke}
              strokeWidth="1"
            />
          ))}

          {shots.map((shot) => {
            const hovered = shot.shotKey === hoveredShotKey;
            const selected = selectedShotKeys.has(shot.shotKey);
            const muted = hasSelection && !selected && !hovered;
            return (
              <circle
                cx={100 + shot.xMm * 4}
                cy={100 - shot.yMm * 4}
                fill={hovered ? "#f4c430" : "#ed5b67"}
                key={shot.shotKey}
                opacity={muted ? 0.2 : hovered || selected ? 1 : 0.78}
                r={hovered || selected ? shotRadius * 1.15 : shotRadius}
                stroke={selected ? "#f4c430" : "#20221f"}
                strokeWidth={selected ? 3 : 1.5}
              >
                <title>
                  Shot {shot.shotNumber}: {shot.score.toFixed(1)}
                </title>
              </circle>
            );
          })}
        </g>
        <line
          className="target-crosshair"
          x1="96"
          x2="104"
          y1="100"
          y2="100"
        />
        <line
          className="target-crosshair"
          x1="100"
          x2="100"
          y1="96"
          y2="104"
        />
      </svg>
    </div>
  );
}
