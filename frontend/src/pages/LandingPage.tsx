// Service introduction (design doc 0): the page the service opens on.
// Says what Retcona is for, what it checks and how a writer uses it, and leads on
// to the login screen — or, for a signed-in author, to the dashboard.
import { Link } from "react-router-dom";
import { useSignedIn } from "../utils/useSignedIn";
import "./LandingPage.css";

const PROBLEMS = [
  {
    title: "외형 불일치",
    body: "초반에 정한 눈 색깔·머리색·흉터·나이가 후반 묘사와 어긋나는 문장을 찾습니다.",
    ready: true,
  },
  {
    title: "장소 오류",
    body: "장소의 지형·특징이 앞에서 쓴 것과 다르거나, 무너진 도시가 다시 번성한 것처럼 그려진 문장을 찾습니다.",
    ready: true,
  },
  {
    title: "시공간 모순",
    body: "이미 죽은 인물이 다시 등장하는 경우를 찾습니다. 회상·유령·부활처럼 정상인 인물은 작가가 표시해 둘 수 있습니다.",
    ready: true,
  },
  {
    title: "성격 이탈 (OOC)",
    body: "확립된 성격과 말투에 맞지 않는 행동을 찾아냅니다.",
    ready: false,
  },
];

const STEPS = [
  {
    title: "원고를 쓰고 저장합니다",
    body: "서비스 안의 에디터에서 화 단위로 씁니다. 쓰는 동안은 이 브라우저에 임시 저장되고, 저장 버튼을 눌렀을 때만 서버로 올라갑니다.",
  },
  {
    title: "검증을 실행합니다",
    body: "저장한 원고에서 인물·장소와 설정에 해당하는 문장을 읽어 이전 화까지 쌓인 기록과 비교합니다. 처음 등장한 인물과 장소는 자동으로 등록됩니다.",
  },
  {
    title: "근거와 함께 확인합니다",
    body: "어긋난 후보는 근거 문장과 함께 나열됩니다. 설정에 반영하거나, 오탐으로 해제하거나, 설정을 보완해 그 항목만 다시 검증할 수 있습니다.",
  },
];

const FEATURES = [
  {
    title: "설정을 미리 쓰지 않아도 됩니다",
    body: "인물·장소 설정은 원고에 처음 나오는 순간 자동으로 만들어집니다. 미리 적어 둔 설정이 있다면 그것이 기준이 됩니다.",
  },
  {
    title: "고치는 것은 항상 작가입니다",
    body: "서비스는 오류를 대신 고치지 않습니다. 의심되는 문장과 근거를 보여 드리고, 판단은 작가가 합니다.",
  },
  {
    title: "하나만 다시 검증합니다",
    body: "빠뜨린 설정 때문에 생긴 오탐이라면, 설정을 보완한 뒤 전체를 다시 돌리지 않고 그 항목만 다시 확인합니다.",
  },
  {
    title: "관계도와 사건 흐름을 한눈에",
    body: "인물 관계 그래프와, 줄거리가 갈라지고 합쳐지는 스토리 타임라인으로 작품의 구조를 정리합니다.",
  },
];

export default function LandingPage() {
  const signedIn = useSignedIn();

  return (
    <div className="landing-page">
      <section className="landing-hero">
        <p className="landing-kicker">웹소설 작가를 위한 설정 일관성 검사</p>
        <h1>연재가 길어져도, 설정은 어긋나지 않게</h1>
        <p className="landing-lead">
          새 화 원고를 올리면 지금까지 쌓인 인물·장소 설정과 어긋나는 문장을 근거와 함께 찾아 보여 드립니다. 매번
          전체 원고를 다시 읽지 않아도 됩니다.
        </p>
        <div className="landing-cta">
          {signedIn ? (
            <Link className="landing-primary" to="/dashboard">
              대시보드로 가기
            </Link>
          ) : (
            <>
              <Link className="landing-primary" to="/login">
                시작하기
              </Link>
              <span className="landing-note">설정을 미리 쓰지 않아도 바로 시작할 수 있습니다.</span>
            </>
          )}
        </div>
      </section>

      <section>
        <h2>이런 어긋남을 찾습니다</h2>
        <p className="landing-sub">화수가 쌓일수록 작가 본인도 기억하기 어려워지는 것들입니다.</p>
        <ul className="landing-grid">
          {PROBLEMS.map((item) => (
            <li key={item.title} className="landing-card">
              <h3>
                {item.title}
                {!item.ready && <span className="landing-badge">준비 중</span>}
              </h3>
              <p>{item.body}</p>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2>이렇게 사용합니다</h2>
        <ol className="landing-steps">
          {STEPS.map((step, index) => (
            <li key={step.title}>
              <span className="landing-step-number">{index + 1}</span>
              <div>
                <h3>{step.title}</h3>
                <p>{step.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section>
        <h2>이런 점이 다릅니다</h2>
        <ul className="landing-grid">
          {FEATURES.map((item) => (
            <li key={item.title} className="landing-card">
              <h3>{item.title}</h3>
              <p>{item.body}</p>
            </li>
          ))}
        </ul>
      </section>

      {!signedIn && (
        <section className="landing-closing">
          <h2>지금 새 화부터 확인해 보세요</h2>
          <Link className="landing-primary" to="/login">
            시작하기
          </Link>
        </section>
      )}
    </div>
  );
}
