"use client";

import { useMemo, useRef, useState } from "react";
import { createPortal, flushSync } from "react-dom";

import { PrintTarget } from "@/components/print-target";
import { formatDateTime } from "@/lib/format";
import {
  calculateAutoTargetZoom,
  DEFAULT_SHOTS_PER_TARGET,
  groupShotsForPrint,
  MAX_PRINT_ZOOM,
  MAX_SHOTS_PER_TARGET,
  MIN_PRINT_ZOOM,
  paginatePrintGroups,
  type PrintTargetGroup,
} from "@/lib/print-layout";
import type { ActivityPhase, TargetKind } from "@/lib/types";

interface PrintPhaseButtonProps {
  laneNumber: number;
  memberId: string;
  phase: ActivityPhase;
  timezone: string;
}

interface PrintDocumentProps extends PrintPhaseButtonProps {
  autoZoom: boolean;
  pages: PrintTargetGroup[][];
  shotsPerTarget: number;
  zoom: number;
}

export function PrintPhaseButton({
  laneNumber,
  memberId,
  phase,
  timezone,
}: PrintPhaseButtonProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [shotsPerTarget, setShotsPerTarget] = useState(
    DEFAULT_SHOTS_PER_TARGET,
  );
  const [zoomPercent, setZoomPercent] = useState(100);
  const [autoZoom, setAutoZoom] = useState(true);
  const [printing, setPrinting] = useState(false);
  const pages = useMemo(
    () => paginatePrintGroups(groupShotsForPrint(phase.shots, shotsPerTarget)),
    [phase.shots, shotsPerTarget],
  );
  const targetCount = pages.reduce((count, page) => count + page.length, 0);

  function handlePrint() {
    dialogRef.current?.close();
    flushSync(() => setPrinting(true));

    const finishPrinting = () => setPrinting(false);
    window.addEventListener("afterprint", finishPrinting, { once: true });
    window.print();
  }

  return (
    <>
      <button
        className="phase-print-button"
        onClick={() => dialogRef.current?.showModal()}
        type="button"
      >
        Print
      </button>

      <dialog className="print-dialog" ref={dialogRef}>
        <form method="dialog">
          <div className="print-dialog-heading">
            <div>
              <p className="section-kicker">Print layout</p>
              <h5>
                {phase.kind === "match"
                  ? `Match relay ${phase.ordinal}`
                  : `Sighter block ${phase.ordinal}`}
              </h5>
            </div>
            <button
              aria-label="Close print settings"
              className="print-dialog-close"
              type="submit"
            >
              ×
            </button>
          </div>

          <div className="print-settings-grid">
            <label>
              <span>Shots per target</span>
              <input
                max={MAX_SHOTS_PER_TARGET}
                min={1}
                onChange={(event) =>
                  setShotsPerTarget(
                    Math.max(
                      1,
                      Math.min(MAX_SHOTS_PER_TARGET, Number(event.target.value)),
                    ),
                  )
                }
                type="number"
                value={shotsPerTarget}
              />
              <small>Choose 1-{MAX_SHOTS_PER_TARGET}. The SIUS-style default is 10.</small>
            </label>

            <div className="print-setting-card">
              <span>Target zoom</span>
              <label className="print-auto-zoom">
                <input
                  checked={autoZoom}
                  onChange={(event) => setAutoZoom(event.target.checked)}
                  type="checkbox"
                />
                <span>Auto-fit each target</span>
              </label>
              <div className="print-zoom-field">
                <input
                  aria-label="Target zoom percentage"
                  disabled={autoZoom}
                  max={MAX_PRINT_ZOOM * 100}
                  min={MIN_PRINT_ZOOM * 100}
                  onChange={(event) => setZoomPercent(Number(event.target.value))}
                  step={25}
                  type="range"
                  value={zoomPercent}
                />
                <output>{autoZoom ? "Auto" : `${zoomPercent}%`}</output>
              </div>
              <small>
                Auto-fit uses the highest zoom that keeps every shot visible.
              </small>
            </div>
          </div>

          <p className="print-layout-summary" aria-live="polite">
            {targetCount} {targetCount === 1 ? "target" : "targets"} across{" "}
            {pages.length} {pages.length === 1 ? "page" : "pages"}. Each target
            includes its own subtotal.
          </p>

          <div className="print-dialog-actions">
            <button className="text-button" type="submit">
              Cancel
            </button>
            <button className="primary-button" onClick={handlePrint} type="button">
              Open print preview
            </button>
          </div>
        </form>
      </dialog>

      {printing
        ? createPortal(
            <PrintDocument
              autoZoom={autoZoom}
              laneNumber={laneNumber}
              memberId={memberId}
              pages={pages}
              phase={phase}
              shotsPerTarget={shotsPerTarget}
              timezone={timezone}
              zoom={zoomPercent / 100}
            />,
            document.body,
          )
        : null}
    </>
  );
}

function PrintDocument({
  autoZoom,
  laneNumber,
  memberId,
  pages,
  phase,
  shotsPerTarget,
  timezone,
  zoom,
}: PrintDocumentProps) {
  const isMatch = phase.kind === "match";
  const phaseTitle = isMatch
    ? `Match relay ${phase.ordinal}`
    : `Sighter block ${phase.ordinal}`;
  const targetLabel = phase.targetKind === "air-pistol" ? "10 m air pistol" : "10 m air rifle";

  return (
    <section className="print-document" aria-label={`${phaseTitle} printout`}>
      {pages.map((groups, pageIndex) => (
        <article className="print-page" key={groups[0]?.number ?? pageIndex}>
          <header className="print-page-header">
            <div>
              <p>RRGC · SIUS practice</p>
              <h1>{phaseTitle}</h1>
            </div>
            <div className="print-header-total">
              <strong>{isMatch ? `Total ${phase.stats.scoreTotal.toFixed(1)}` : "Sighters"}</strong>
              <span>
                Page {pageIndex + 1} / {pages.length}
              </span>
            </div>
          </header>

          <div className="print-page-meta">
            <span>Member {memberId}</span>
            <span>Lane {laneNumber}</span>
            <span>{formatDateTime(phase.startedAt, timezone)}</span>
            <span>{targetLabel}</span>
            <span>{shotsPerTarget} shots / target</span>
            <span>
              {autoZoom
                ? "Auto-fit zoom"
                : `${Math.round(zoom * 100)}% zoom`}
            </span>
          </div>

          <div className="print-target-grid">
            {groups.map((group) => (
              <PrintTargetCard
                autoZoom={autoZoom}
                group={group}
                key={group.number}
                targetKind={phase.targetKind}
                zoom={zoom}
              />
            ))}
          </div>

          <footer className="print-page-footer">
            <span>Black-and-white practice record</span>
            <span>{phase.stats.shotCount} shots</span>
          </footer>
        </article>
      ))}
    </section>
  );
}

function PrintTargetCard({
  autoZoom,
  group,
  targetKind,
  zoom,
}: {
  autoZoom: boolean;
  group: PrintTargetGroup;
  targetKind: TargetKind;
  zoom: number;
}) {
  const firstShot = group.shots[0]?.shotNumber;
  const lastShot = group.shots.at(-1)?.shotNumber;
  const shotLabel =
    firstShot === lastShot ? `Shot ${firstShot}` : `Shots ${firstShot}-${lastShot}`;
  const scoreColumns = Math.min(group.shots.length, 10);
  const targetZoom = autoZoom
    ? calculateAutoTargetZoom(group.shots, targetKind)
    : zoom;

  return (
    <figure className="print-target-card">
      <figcaption>
        <span>Target {group.number} · {shotLabel}</span>
        <strong>Subtotal {(group.scoreTenthsTotal / 10).toFixed(1)}</strong>
      </figcaption>
      <div className="print-target-plot">
        <PrintTarget
          shots={group.shots}
          targetKind={targetKind}
          zoom={targetZoom}
        />
      </div>
      <div
        className="print-score-strip"
        style={{ gridTemplateColumns: `repeat(${scoreColumns}, minmax(0, 1fr))` }}
      >
        {group.shots.map((shot) => (
          <span key={shot.shotKey}>{shot.score.toFixed(1)}</span>
        ))}
      </div>
    </figure>
  );
}
