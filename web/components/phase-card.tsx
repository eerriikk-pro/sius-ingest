"use client";

import { useMemo, useState } from "react";

import { ShotTarget } from "@/components/shot-target";
import type { ActivityPhase, ActivityShot } from "@/lib/types";

interface PhaseCardProps {
  phase: ActivityPhase;
}

export function PhaseCard({ phase }: PhaseCardProps) {
  const [hoveredShotKey, setHoveredShotKey] = useState<string | null>(null);
  const [selectedShotKeys, setSelectedShotKeys] = useState<Set<string>>(
    () => new Set(),
  );
  const series = useMemo(() => chunkShots(phase.shots, 10), [phase.shots]);
  const isMatch = phase.kind === "match";
  const title = isMatch
    ? `Match relay ${phase.ordinal}`
    : `Sighter block ${phase.ordinal}`;

  function toggleShot(shotKey: string) {
    setSelectedShotKeys((current) => {
      const next = new Set(current);
      if (next.has(shotKey)) {
        next.delete(shotKey);
      } else {
        next.add(shotKey);
      }
      return next;
    });
  }

  function toggleSeries(shots: ActivityShot[]) {
    setSelectedShotKeys((current) => {
      const next = new Set(current);
      const allSelected = shots.every((shot) => next.has(shot.shotKey));
      for (const shot of shots) {
        if (allSelected) {
          next.delete(shot.shotKey);
        } else {
          next.add(shot.shotKey);
        }
      }
      return next;
    });
  }

  return (
    <section className={`phase-card phase-${phase.kind}`}>
      <header className="phase-header">
        <div>
          <span className={`phase-badge phase-badge-${phase.kind}`}>
            {isMatch ? "Match" : "Sighters"}
          </span>
          <h4>{title}</h4>
        </div>
        <div className="phase-stats">
          <span>
            <strong>{phase.stats.shotCount}</strong> shots
          </span>
          <span>
            <strong>{phase.stats.scoreTotal.toFixed(1)}</strong> total
          </span>
          <span>
            <strong>
              {phase.stats.averageScore === null
                ? "—"
                : phase.stats.averageScore.toFixed(2)}
            </strong>{" "}
            avg
          </span>
          <span title="Target type inferred from the SIUS score encoding">
            {phase.targetKind === "air-pistol" ? "Air pistol" : "Air rifle"}
          </span>
        </div>
      </header>

      <div className="phase-content">
        <ShotTarget
          hoveredShotKey={hoveredShotKey}
          selectedShotKeys={selectedShotKeys}
          shots={phase.shots}
          targetKind={phase.targetKind}
        />

        <div className="shot-series" aria-label={`${title} shot list`}>
          {series.map((shots, seriesIndex) => {
            const total = shots.reduce(
              (sum, shot) => sum + shot.scoreTenths,
              0,
            );
            const label = isMatch
              ? `Series ${seriesIndex + 1}`
              : series.length === 1
                ? "Sighters"
                : `Sighters ${seriesIndex * 10 + 1}–${seriesIndex * 10 + shots.length}`;
            return (
              <div className="series-block" key={shots[0]?.shotKey ?? seriesIndex}>
                <button
                  className="series-heading"
                  onClick={() => toggleSeries(shots)}
                  type="button"
                >
                  <span>{label}</span>
                  <strong>{(total / 10).toFixed(1)}</strong>
                </button>
                <div className="shot-grid">
                  {shots.map((shot) => {
                    const selected = selectedShotKeys.has(shot.shotKey);
                    return (
                      <button
                        aria-pressed={selected}
                        className={`shot-chip ${selected ? "shot-chip-selected" : ""}`}
                        key={shot.shotKey}
                        onClick={() => toggleShot(shot.shotKey)}
                        onFocus={() => setHoveredShotKey(shot.shotKey)}
                        onBlur={() => setHoveredShotKey(null)}
                        onMouseEnter={() => setHoveredShotKey(shot.shotKey)}
                        onMouseLeave={() => setHoveredShotKey(null)}
                        title={`Shot ${shot.shotNumber}: ${shot.score.toFixed(1)} at ${shot.deviceTime}`}
                        type="button"
                      >
                        <small>{shot.shotNumber}</small>
                        <strong>{shot.score.toFixed(1)}</strong>
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}

          {selectedShotKeys.size > 0 ? (
            <button
              className="clear-button"
              onClick={() => setSelectedShotKeys(new Set())}
              type="button"
            >
              Clear {selectedShotKeys.size} selected
            </button>
          ) : (
            <p className="interaction-hint">
              Hover a score to locate it. Select shots or a series to compare.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

function chunkShots(shots: ActivityShot[], size: number): ActivityShot[][] {
  const chunks: ActivityShot[][] = [];
  for (let index = 0; index < shots.length; index += size) {
    chunks.push(shots.slice(index, index + size));
  }
  return chunks;
}
