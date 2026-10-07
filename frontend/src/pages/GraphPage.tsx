// Per-novel relationship graph · timeline screen (design doc 2.6, 9)
// Top tabs switch between the character relationship graph (9.2) and the story timeline graph (9.3).
// The relationship graph is drawn by components/RelationGraph (d3-force); the timeline tab comes later.
// The author enters relations here: nothing reads them out of the manuscript yet.
import { FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import RelationGraph from "../components/RelationGraph";
import { ApiError, describeError } from "../api/client";
import {
  RELATION_TYPE_MAX_LENGTH,
  RELATION_TYPE_SUGGESTIONS,
  createRelation,
  deleteRelation,
  listRelations,
  updateRelation,
} from "../api/relations";
import type { RelationInput, RelationPublic } from "../api/relations";
import { listCharacters } from "../api/settings";
import type { CharacterPublic } from "../api/settings";
import "./GraphPage.css";

const EMPTY_FORM: RelationInput = { from_id: "", to_id: "", relation_type: "", directed: false };

function describeRelationError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 409) return "이미 같은 관계가 있습니다.";
    if (err.status === 404) return "캐릭터를 찾을 수 없습니다. 화면을 새로고침해 주세요.";
  }
  return describeError(err);
}

export default function GraphPage() {
  const { novelId } = useParams<{ novelId: string }>();
  const [characters, setCharacters] = useState<CharacterPublic[] | null>(null);
  const [relations, setRelations] = useState<RelationPublic[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [form, setForm] = useState<RelationInput>(EMPTY_FORM);
  // The relation the form edits; null: it adds one.
  const [editingId, setEditingId] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function load() {
    if (!novelId) return;
    setLoadError(null);
    Promise.all([listCharacters(novelId), listRelations(novelId)])
      .then(([characterList, relationList]) => {
        setCharacters(characterList);
        setRelations(relationList);
      })
      .catch((err) => setLoadError(describeError(err)));
  }

  useEffect(() => {
    setCharacters(null);
    setRelations([]);
    setForm(EMPTY_FORM);
    setEditingId(null);
    load();
  }, [novelId]);

  const names = new Map((characters ?? []).map((character) => [character.id, character.name]));

  function startEditing(relation: RelationPublic) {
    setEditingId(relation.id);
    setForm({
      from_id: relation.from_id,
      to_id: relation.to_id,
      relation_type: relation.relation_type,
      directed: relation.directed,
    });
    setFormError(null);
  }

  function stopEditing() {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setFormError(null);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!novelId || busy) return;
    const input = { ...form, relation_type: form.relation_type.trim() };
    if (!input.from_id || !input.to_id) {
      setFormError("관계를 맺을 두 캐릭터를 선택해 주세요.");
      return;
    }
    if (input.from_id === input.to_id) {
      setFormError("서로 다른 두 캐릭터를 선택해 주세요.");
      return;
    }
    if (!input.relation_type) {
      setFormError("관계 종류를 입력해 주세요.");
      return;
    }
    setBusy(true);
    setFormError(null);
    try {
      if (editingId) {
        const saved = await updateRelation(novelId, editingId, input);
        setRelations((prev) => prev.map((relation) => (relation.id === saved.id ? saved : relation)));
      } else {
        const saved = await createRelation(novelId, input);
        setRelations((prev) => [...prev, saved]);
      }
      stopEditing();
    } catch (err) {
      setFormError(describeRelationError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(relation: RelationPublic) {
    if (!novelId || busy) return;
    setBusy(true);
    setFormError(null);
    try {
      await deleteRelation(novelId, relation.id);
      setRelations((prev) => prev.filter((other) => other.id !== relation.id));
      if (editingId === relation.id) stopEditing();
    } catch (err) {
      setFormError(describeRelationError(err));
    } finally {
      setBusy(false);
    }
  }

  const describe = (relation: RelationPublic) =>
    `${names.get(relation.from_id) ?? "?"} ${relation.directed ? "→" : "—"} ${names.get(relation.to_id) ?? "?"}`;

  return (
    <div className="graph-page">
      <Link className="back-link" to="/mypage">
        ← 마이페이지
      </Link>
      <div className="section-header">
        <h1>관계 그래프 · 타임라인</h1>
        <div className="graph-tabs" role="tablist">
          <button type="button" role="tab" aria-selected className="active">
            관계 그래프
          </button>
          <button type="button" role="tab" aria-selected={false} disabled title="준비 중입니다.">
            타임라인
          </button>
        </div>
      </div>

      {loadError && (
        <p className="graph-error">
          {loadError} <button type="button" onClick={load}>다시 시도</button>
        </p>
      )}

      {characters === null ? (
        !loadError && <p>불러오는 중...</p>
      ) : characters.length < 2 ? (
        <p className="empty-state">
          관계를 그리려면 캐릭터가 두 명 이상 필요합니다.{" "}
          <Link to={`/novels/${novelId}/settings`}>설정 관리</Link>에서 캐릭터를 추가하거나, 원고를 검증하면 등장한
          인물이 자동으로 등록됩니다.
        </p>
      ) : (
        <div className="graph-layout">
          <div className="graph-canvas">
            <RelationGraph
              characters={characters}
              relations={relations}
              selectedRelationId={editingId}
              onSelectRelation={(id) => {
                const relation = relations.find((other) => other.id === id);
                if (relation) startEditing(relation);
              }}
            />
            <p className="graph-hint">캐릭터는 끌어서 옮길 수 있고, 선을 누르면 그 관계를 수정할 수 있습니다.</p>
          </div>

          <div className="graph-panel">
            <form className="relation-form" onSubmit={handleSubmit}>
              <h2>{editingId ? "관계 수정" : "관계 추가"}</h2>
              <label>
                {form.directed ? "누가 (출발)" : "캐릭터 1"}
                <select value={form.from_id} onChange={(e) => setForm({ ...form, from_id: e.target.value })}>
                  <option value="">선택</option>
                  {characters.map((character) => (
                    <option key={character.id} value={character.id}>
                      {character.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {form.directed ? "누구에게 (도착)" : "캐릭터 2"}
                <select value={form.to_id} onChange={(e) => setForm({ ...form, to_id: e.target.value })}>
                  <option value="">선택</option>
                  {characters.map((character) => (
                    <option key={character.id} value={character.id}>
                      {character.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                관계 종류
                <input
                  type="text"
                  list="relation-type-suggestions"
                  value={form.relation_type}
                  onChange={(e) => setForm({ ...form, relation_type: e.target.value })}
                  maxLength={RELATION_TYPE_MAX_LENGTH}
                  placeholder="예: 가족, 라이벌, 스승"
                />
                <datalist id="relation-type-suggestions">
                  {RELATION_TYPE_SUGGESTIONS.map((suggestion) => (
                    <option key={suggestion} value={suggestion} />
                  ))}
                </datalist>
              </label>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={form.directed}
                  onChange={(e) => setForm({ ...form, directed: e.target.checked })}
                />
                한쪽 방향의 관계 (예: 스승 → 제자)
              </label>
              {formError && <p className="graph-error">{formError}</p>}
              <div className="form-actions">
                <button type="submit" disabled={busy}>
                  {busy ? "저장 중..." : editingId ? "수정 저장" : "추가"}
                </button>
                {editingId && (
                  <button type="button" onClick={stopEditing} disabled={busy}>
                    취소
                  </button>
                )}
              </div>
            </form>

            <h2>관계 목록 ({relations.length})</h2>
            {relations.length === 0 ? (
              <p className="empty-state">아직 등록한 관계가 없습니다.</p>
            ) : (
              <ul className="relation-list">
                {relations.map((relation) => (
                  <li key={relation.id} className={relation.id === editingId ? "selected" : undefined}>
                    <span className="relation-people">{describe(relation)}</span>
                    <span className="relation-type">{relation.relation_type}</span>
                    <button type="button" onClick={() => startEditing(relation)} disabled={busy}>
                      수정
                    </button>
                    <button type="button" onClick={() => handleDelete(relation)} disabled={busy}>
                      삭제
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
