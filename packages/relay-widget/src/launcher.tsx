"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ComponentType } from "react";
import "@vitalos/design-tokens/relay.css";
import "./launcher.css";
import type { PanelProps } from "./panel";
import { hasSeen, loadConversation, markSeen, rememberOpen, wasOpen } from "./storage";

export interface RelayLauncherProps {
  /** Turnstile site key (invisible); loaded only when the panel opens. */
  turnstileSiteKey?: string | undefined;
  /** Class names that expose the panel fonts (next/font variables). */
  fontClassName?: string;
  symbolSrc: string;
  privacyUrl: string;
}

let panelModule: Promise<{ Panel: ComponentType<PanelProps> }> | null = null;
/** The panel bundle loads on first intent (hover, focus, click), never on page load. */
const loadPanel = () => (panelModule ??= import("./panel"));

/**
 * Vitalos Relay launcher (section 4.2): a fixed square speech tile, labelled "Ask Vitalos" on
 * desktop until the first open. No dependencies, no network until the visitor interacts, no
 * auto-open, no sound.
 */
export function RelayLauncher(props: RelayLauncherProps) {
  const [Panel, setPanel] = useState<ComponentType<PanelProps> | null>(null);
  const [open, setOpen] = useState(false);
  const [seen, setSeen] = useState(true);
  const [unread, setUnread] = useState(0);
  const buttonRef = useRef<HTMLButtonElement>(null);

  const ensurePanel = useCallback(async () => {
    const mod = await loadPanel();
    setPanel(() => mod.Panel);
  }, []);

  useEffect(() => {
    setSeen(hasSeen());
    const stored = loadConversation();
    const resume = new URLSearchParams(window.location.search).get("relay") === "resume";
    // Returning visitors: reopen in the same tab session, or keep watching for a person's reply.
    if (resume || wasOpen()) {
      void ensurePanel().then(() => setOpen(true));
    } else if (stored?.personJoined) {
      if ("requestIdleCallback" in window) window.requestIdleCallback(() => void ensurePanel());
      else setTimeout(() => void ensurePanel(), 2000);
    }
  }, [ensurePanel]);

  const toggle = async () => {
    if (!Panel) await ensurePanel();
    const next = !open;
    setOpen(next);
    rememberOpen(next);
    if (next) {
      markSeen();
      setSeen(true);
      setUnread(0);
    }
  };

  const close = useCallback((returnFocus: boolean) => {
    setOpen(false);
    rememberOpen(false);
    // The launcher is hidden while the panel is open on small screens: focus it once it is back.
    if (returnFocus) requestAnimationFrame(() => buttonRef.current?.focus());
  }, []);

  // WCAG 2.5.3 Label in Name: while the visible "Ask Vitalos" label is rendered, the accessible
  // name starts with it, so speech users can say what they see.
  const label = `${seen ? "" : "Ask Vitalos. "}${
    unread > 0
      ? `Open chat with Relay. ${unread} new ${unread === 1 ? "reply" : "replies"} from the Vitalos team`
      : "Open chat with Relay, the Vitalos assistant"
  }`;

  return (
    <div className={`relay-root ${props.fontClassName ?? ""}`}>
      <div className={`relay-launcher-wrap${open ? " relay-launcher-wrap--open" : ""}`}>
        <div className="relay-launcher-keyline">
          <button
            ref={buttonRef}
            type="button"
            className={`relay-launcher${seen ? "" : " relay-launcher--labelled"}`}
            aria-label={label}
            aria-expanded={open}
            aria-controls="relay-panel"
            onPointerEnter={() => void loadPanel()}
            onFocus={() => void loadPanel()}
            onClick={() => void toggle()}
          >
            {!seen && <span className="relay-launcher-label">Ask Vitalos</span>}
            <span className="relay-launcher-tile">
              <img src={props.symbolSrc} alt="" width={44} height={44} decoding="async" />
            </span>
          </button>
        </div>
        {unread > 0 && (
          <span className="relay-launcher-badge" aria-hidden="true">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </div>
      {Panel && (
        <Panel
          open={open}
          onClose={close}
          onUnread={(n) => setUnread(open ? 0 : n)}
          turnstileSiteKey={props.turnstileSiteKey}
          symbolSrc={props.symbolSrc}
          privacyUrl={props.privacyUrl}
        />
      )}
    </div>
  );
}
