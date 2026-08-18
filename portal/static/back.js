/* ── 「← 포탈로」 를 눌렀을 때 ──────────────────────────────────
 *
 * 포털에서 앱을 누르면 새 탭이 열린다. 그 탭에서 「← 포탈로」 를 누르면
 * 지금까지는 **그 탭이 포털로 바뀌었다.** 앱을 셋 열고 셋 다 돌아오면
 * 포털 탭이 넷이 된다. 돌아온 게 아니라 늘어난 것이다.
 *
 * 그래서 이 탭이 포털에서 열린 것이면 **포털 탭으로 옮겨 가고 이 탭은 닫는다.**
 * 주소를 직접 쳐서 들어왔거나 포털 탭이 이미 닫혔으면 예전처럼 그냥 이동한다.
 *
 * 이 파일은 포털이 준다. 앱마다 복사해 두면 한 곳을 고쳐도 다른 앱은
 * 옛 동작으로 남는다. 앱은 아래 한 줄만 넣으면 된다.
 *
 *     <script src="/back.js" defer></script>
 *
 * 대상은 class="backportal" 인 링크다. 이름을 그렇게 맞춰 두면 된다.
 * ───────────────────────────────────────────────────────────── */
(function () {
  "use strict";

  function goPortal(e) {
    var opener = null;
    // 다른 출처의 창이면 opener 를 읽는 것만으로도 오류가 난다.
    try { opener = window.opener; } catch (err) { opener = null; }

    if (!opener || opener.closed) return;    // 그냥 링크대로 이동한다

    e.preventDefault();
    try { opener.focus(); } catch (err) {}

    window.close();

    /* 닫히지 않을 수도 있다. 브라우저는 "스크립트가 연 창"만 닫게 해 주는데,
       설정이나 브라우저에 따라 거절당한다. 그때 아무 일도 안 일어나면
       버튼이 고장 난 것처럼 보이므로, 잠깐 기다렸다가 그냥 이동한다. */
    setTimeout(function () {
      if (!window.closed) location.href = "/";
    }, 150);
  }

  function wire() {
    var links = document.querySelectorAll("a.backportal, .backportal a, [data-backportal]");
    for (var i = 0; i < links.length; i++) {
      links[i].addEventListener("click", goPortal);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
})();
