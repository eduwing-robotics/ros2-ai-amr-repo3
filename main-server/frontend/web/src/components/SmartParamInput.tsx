/** 경로·쿼리 파라미터 스마트 입력 — 목록 + 직접 입력 폴백 (PHASE_49-D). */

const ROBOT_PARAM = /^(robot_id|robot_name)$/i;
const MAP_PARAM = /^map_id$/i;
const COMMAND_PARAM = /^command_id$/i;

export function smartParamKind(name: string): "robot" | "map" | "command" | null {
  if (ROBOT_PARAM.test(name)) return "robot";
  if (MAP_PARAM.test(name)) return "map";
  if (COMMAND_PARAM.test(name)) return "command";
  return null;
}

export function SmartParamInput({
  name,
  value,
  onChange,
  options,
  placeholder,
}: {
  name: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
  placeholder?: string;
}) {
  const listId = `smart-param-${name}`;
  const inList = value !== "" && options.includes(value);

  return (
    <span className="smart-param-input">
      {options.length > 0 ? (
        <select
          className="filter mono smart-param-pick"
          value={inList ? value : ""}
          onChange={(e) => {
            if (e.target.value) onChange(e.target.value);
          }}
          aria-label={`${name} 목록`}
        >
          <option value="">목록에서 선택…</option>
          {options.map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </select>
      ) : null}
      <input
        className="search mono"
        list={options.length ? listId : undefined}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder || "직접 입력"}
      />
      {options.length > 0 ? (
        <datalist id={listId}>
          {options.map((o) => <option key={o} value={o} />)}
        </datalist>
      ) : null}
    </span>
  );
}
