// The story timeline tab (design doc 2.6, 9.3): the graph of a novel's events
// and the forms the author enters them with — nothing reads events out of the
// manuscript yet.
import { FormEvent, useEffect, useState } from "react";
import TimelineGraph from "./TimelineGraph";
import { ApiError, describeError } from "../api/client";
import {
  BRANCH_REASON_MAX_LENGTH,
  EPISODE_MAX,
  LINK_TYPES,
  SUMMARY_MAX_LENGTH,
  createEvent,
  createLink,
  deleteEvent,
  deleteLink,
  listEvents,
  listLinks,
  listLocations,
  updateEvent,
  updateLink,
} from "../api/events";
import type { EventInput, EventPublic, LinkInput, LinkPublic, LinkType, LocationPublic } from "../api/events";
import type { CharacterPublic } from "../api/settings";

const EMPTY_EVENT: EventInput = { episode_index: 1, summary: "", character_ids: [], location_ids: [] };
const EMPTY_LINK: LinkInput = { from_id: "", to_id: "", link_type: "sequential", branch_reason: null };

function describeTimelineError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 409) return "이미 같은 연결이 있습니다.";
    if (err.status === 404) return "대상을 찾을 수 없습니다. 화면을 새로고침해 주세요.";
  }
  return describeError(err);
}

// Oldest first within an episode, as the server lists them (stable, so what was
// already in order and what was just added keep theirs).
function byEpisode(events: EventPublic[]): EventPublic[] {
  return [...events].sort((a, b) => a.episode_index - b.episode_index);
}

function toggled(ids: string[], id: string): string[] {
  return ids.includes(id) ? ids.filter((other) => other !== id) : [...ids, id];
}

interface Props {
  novelId: string;
  characters: CharacterPublic[];
}

export default function TimelinePanel({ novelId, characters }: Props) {
  const [events, setEvents] = useState<EventPublic[] | null>(null);
  const [links, setLinks] = useState<LinkPublic[]>([]);
  const [locations, setLocations] = useState<LocationPublic[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [eventForm, setEventForm] = useState<EventInput>(EMPTY_EVENT);
  const [editingEventId, setEditingEventId] = useState<string | null>(null);
  const [linkForm, setLinkForm] = useState<LinkInput>(EMPTY_LINK);
  const [editingLinkId, setEditingLinkId] = useState<string | null>(null);
  const [eventError, setEventError] = useState<string | null>(null);
  const [linkError, setLinkError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function load() {
    setLoadError(null);
    Promise.all([listEvents(novelId), listLinks(novelId), listLocations(novelId)])
      .then(([eventList, linkList, locationList]) => {
        setEvents(eventList);
        setLinks(linkList);
        setLocations(locationList);
      })
      .catch((err) => setLoadError(describeError(err)));
  }

  useEffect(load, [novelId]);

  const characterNames = new Map(characters.map((character) => [character.id, character.name]));
  const locationNames = new Map(locations.map((location) => [location.id, location.name]));
  const eventLabel = (event: EventPublic) => `${event.episode_index}화 · ${event.summary}`;
  const labelOf = (id: string) => {
    const event = (events ?? []).find((other) => other.id === id);
    return event ? eventLabel(event) : "?";
  };

  function startEditingEvent(event: EventPublic) {
    setEditingEventId(event.id);
    setEventForm({
      episode_index: event.episode_index,
      summary: event.summary,
      character_ids: event.character_ids,
      location_ids: event.location_ids,
    });
    setEventError(null);
  }

  function stopEditingEvent() {
    setEditingEventId(null);
    setEventForm(EMPTY_EVENT);
    setEventError(null);
  }

  function startEditingLink(link: LinkPublic) {
    setEditingLinkId(link.id);
    setLinkForm({
      from_id: link.from_id,
      to_id: link.to_id,
      link_type: link.link_type,
      branch_reason: link.branch_reason,
    });
    setLinkError(null);
  }

  function stopEditingLink() {
    setEditingLinkId(null);
    setLinkForm(EMPTY_LINK);
    setLinkError(null);
  }

  async function handleEventSubmit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    const input = { ...eventForm, summary: eventForm.summary.trim() };
    if (!Number.isInteger(input.episode_index) || input.episode_index < 1 || input.episode_index > EPISODE_MAX) {
      setEventError(`화 번호는 1 이상 ${EPISODE_MAX} 이하의 정수로 입력해 주세요.`);
      return;
    }
    if (!input.summary) {
      setEventError("사건 내용을 입력해 주세요.");
      return;
    }
    setBusy(true);
    setEventError(null);
    try {
      if (editingEventId) {
        const saved = await updateEvent(novelId, editingEventId, input);
        setEvents((prev) => byEpisode((prev ?? []).map((event) => (event.id === saved.id ? saved : event))));
        stopEditingEvent();
      } else {
        const saved = await createEvent(novelId, input);
        setEvents((prev) => byEpisode([...(prev ?? []), saved]));
        // Events come in a run of one episode: keep its number for the next.
        setEventForm({ ...EMPTY_EVENT, episode_index: saved.episode_index });
        setEventError(null);
      }
    } catch (err) {
      setEventError(describeTimelineError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleEventDelete(event: EventPublic) {
    if (busy) return;
    setBusy(true);
    setEventError(null);
    try {
      await deleteEvent(novelId, event.id);
      setEvents((prev) => (prev ?? []).filter((other) => other.id !== event.id));
      // The links to and from it went with it.
      setLinks((prev) => prev.filter((link) => link.from_id !== event.id && link.to_id !== event.id));
      if (editingEventId === event.id) stopEditingEvent();
      if (editingLinkId && links.some((link) => link.id === editingLinkId && (link.from_id === event.id || link.to_id === event.id))) {
        // The link being edited went with it.
        stopEditingLink();
      } else {
        // A link being drafted or edited that picked it for one end: that end is gone.
        setLinkForm((prev) => ({
          ...prev,
          from_id: prev.from_id === event.id ? "" : prev.from_id,
          to_id: prev.to_id === event.id ? "" : prev.to_id,
        }));
      }
    } catch (err) {
      setEventError(describeTimelineError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleLinkSubmit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    const input = { ...linkForm, branch_reason: linkForm.link_type === "branch" ? linkForm.branch_reason?.trim() || null : null };
    if (!input.from_id || !input.to_id) {
      setLinkError("연결할 두 사건을 선택해 주세요.");
      return;
    }
    if (input.from_id === input.to_id) {
      setLinkError("서로 다른 두 사건을 선택해 주세요.");
      return;
    }
    setBusy(true);
    setLinkError(null);
    try {
      if (editingLinkId) {
        const saved = await updateLink(novelId, editingLinkId, input);
        setLinks((prev) => prev.map((link) => (link.id === saved.id ? saved : link)));
      } else {
        const saved = await createLink(novelId, input);
        setLinks((prev) => [...prev, saved]);
      }
      stopEditingLink();
    } catch (err) {
      setLinkError(describeTimelineError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleLinkDelete(link: LinkPublic) {
    if (busy) return;
    setBusy(true);
    setLinkError(null);
    try {
      await deleteLink(novelId, link.id);
      setLinks((prev) => prev.filter((other) => other.id !== link.id));
      if (editingLinkId === link.id) stopEditingLink();
    } catch (err) {
      setLinkError(describeTimelineError(err));
    } finally {
      setBusy(false);
    }
  }

  if (loadError) {
    return (
      <p className="graph-error">
        {loadError} <button type="button" onClick={load}>다시 시도</button>
      </p>
    );
  }
  if (events === null) return <p>불러오는 중...</p>;

  return (
    <div className="graph-layout timeline-layout">
      <div className="graph-canvas">
        {events.length === 0 ? (
          <p className="empty-state">아직 등록한 사건이 없습니다. 오른쪽에서 사건을 추가해 보세요.</p>
        ) : (
          <TimelineGraph
            events={events}
            links={links}
            names={characterNames}
            selectedEventId={editingEventId}
            selectedLinkId={editingLinkId}
            onSelectEvent={(id) => {
              const event = events.find((other) => other.id === id);
              // Not while a save or delete is under way: it would swap the form out from under it.
              if (event && !busy) startEditingEvent(event);
            }}
            onSelectLink={(id) => {
              const link = links.find((other) => other.id === id);
              if (link && !busy) startEditingLink(link);
            }}
          />
        )}
        <p className="graph-hint">
          사건은 화 순서대로 왼쪽에서 오른쪽으로 놓입니다. 사건이나 연결선을 누르면 수정할 수 있습니다. 갈라지거나
          합쳐지는 줄거리는 연결의 종류로 표시하세요.
        </p>
      </div>

      <div className="graph-panel">
        <form className="relation-form" onSubmit={handleEventSubmit}>
          <h2>{editingEventId ? "사건 수정" : "사건 추가"}</h2>
          <label>
            화
            <input
              type="number"
              min={1}
              max={EPISODE_MAX}
              step={1}
              value={Number.isNaN(eventForm.episode_index) ? "" : eventForm.episode_index}
              onChange={(e) => setEventForm({ ...eventForm, episode_index: e.target.valueAsNumber })}
            />
          </label>
          <label>
            사건 내용
            <textarea
              value={eventForm.summary}
              onChange={(e) => setEventForm({ ...eventForm, summary: e.target.value })}
              maxLength={SUMMARY_MAX_LENGTH}
              rows={3}
              placeholder="예: 레온과 세린이 함께 마을을 떠난다"
            />
          </label>
          <fieldset className="member-picker">
            <legend>등장 인물</legend>
            {characters.length === 0 ? (
              <span className="alias-hint">등록된 캐릭터가 없습니다.</span>
            ) : (
              characters.map((character) => (
                <label key={character.id} className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={eventForm.character_ids.includes(character.id)}
                    onChange={() =>
                      setEventForm({ ...eventForm, character_ids: toggled(eventForm.character_ids, character.id) })
                    }
                  />
                  {character.name}
                </label>
              ))
            )}
          </fieldset>
          <fieldset className="member-picker">
            <legend>장소</legend>
            {locations.length === 0 ? (
              <span className="alias-hint">원고에서 등록된 장소가 아직 없습니다.</span>
            ) : (
              locations.map((location) => (
                <label key={location.id} className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={eventForm.location_ids.includes(location.id)}
                    onChange={() =>
                      setEventForm({ ...eventForm, location_ids: toggled(eventForm.location_ids, location.id) })
                    }
                  />
                  {location.name}
                </label>
              ))
            )}
          </fieldset>
          {eventError && <p className="graph-error">{eventError}</p>}
          <div className="form-actions">
            <button type="submit" disabled={busy}>
              {busy ? "저장 중..." : editingEventId ? "수정 저장" : "추가"}
            </button>
            {editingEventId && (
              <button type="button" onClick={stopEditingEvent} disabled={busy}>
                취소
              </button>
            )}
          </div>
        </form>

        <h2>사건 목록 ({events.length})</h2>
        {events.length === 0 ? (
          <p className="empty-state">아직 등록한 사건이 없습니다.</p>
        ) : (
          <ul className="relation-list">
            {events.map((event) => (
              <li key={event.id} className={event.id === editingEventId ? "selected" : undefined}>
                <span className="relation-people">
                  {eventLabel(event)}
                  <span className="relation-type">
                    {[
                      ...event.character_ids.map((id) => characterNames.get(id)),
                      ...event.location_ids.map((id) => locationNames.get(id)),
                    ]
                      .filter(Boolean)
                      .join(", ")}
                  </span>
                </span>
                <button type="button" onClick={() => startEditingEvent(event)} disabled={busy}>
                  수정
                </button>
                <button type="button" onClick={() => handleEventDelete(event)} disabled={busy}>
                  삭제
                </button>
              </li>
            ))}
          </ul>
        )}

        <form className="relation-form" onSubmit={handleLinkSubmit}>
          <h2>{editingLinkId ? "연결 수정" : "사건 연결"}</h2>
          <label>
            앞의 사건
            <select value={linkForm.from_id} onChange={(e) => setLinkForm({ ...linkForm, from_id: e.target.value })}>
              <option value="">선택</option>
              {events.map((event) => (
                <option key={event.id} value={event.id}>
                  {eventLabel(event)}
                </option>
              ))}
            </select>
          </label>
          <label>
            이어지는 사건
            <select value={linkForm.to_id} onChange={(e) => setLinkForm({ ...linkForm, to_id: e.target.value })}>
              <option value="">선택</option>
              {events.map((event) => (
                <option key={event.id} value={event.id}>
                  {eventLabel(event)}
                </option>
              ))}
            </select>
          </label>
          <label>
            연결 종류
            <select
              value={linkForm.link_type}
              onChange={(e) => setLinkForm({ ...linkForm, link_type: e.target.value as LinkType })}
            >
              {Object.entries(LINK_TYPES).map(([code, label]) => (
                <option key={code} value={code}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          {linkForm.link_type === "branch" && (
            <label>
              갈라진 이유 (선택)
              <input
                type="text"
                value={linkForm.branch_reason ?? ""}
                onChange={(e) => setLinkForm({ ...linkForm, branch_reason: e.target.value })}
                maxLength={BRANCH_REASON_MAX_LENGTH}
                placeholder="예: 세린이 마을에 남음"
              />
            </label>
          )}
          {linkError && <p className="graph-error">{linkError}</p>}
          <div className="form-actions">
            <button type="submit" disabled={busy || events.length < 2}>
              {busy ? "저장 중..." : editingLinkId ? "수정 저장" : "연결"}
            </button>
            {editingLinkId && (
              <button type="button" onClick={stopEditingLink} disabled={busy}>
                취소
              </button>
            )}
          </div>
        </form>

        <h2>연결 목록 ({links.length})</h2>
        {links.length === 0 ? (
          <p className="empty-state">아직 연결한 사건이 없습니다.</p>
        ) : (
          <ul className="relation-list">
            {links.map((link) => (
              <li key={link.id} className={link.id === editingLinkId ? "selected" : undefined}>
                <span className="relation-people">
                  {labelOf(link.from_id)} → {labelOf(link.to_id)}
                  <span className="relation-type">
                    {LINK_TYPES[link.link_type]}
                    {link.branch_reason ? ` · ${link.branch_reason}` : ""}
                  </span>
                </span>
                <button type="button" onClick={() => startEditingLink(link)} disabled={busy}>
                  수정
                </button>
                <button type="button" onClick={() => handleLinkDelete(link)} disabled={busy}>
                  삭제
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
