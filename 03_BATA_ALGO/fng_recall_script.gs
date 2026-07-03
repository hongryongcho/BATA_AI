/**
 * F&G Recall — Google Apps Script
 * ============================================================
 * 구글 시트 상단에 "F&G Recall" 버튼을 만들어 이 스크립트를 연결하면
 * CNN F&G 실시간 값을 새로 조회해서 Summary 탭을 업데이트합니다.
 *
 * [설치 방법]
 * 1. Google Sheet 에서 Extensions(확장 프로그램) > Apps Script 열기
 * 2. 이 파일 전체를 붙여넣고 저장 (Ctrl+S)
 * 3. 시트로 돌아와서 Insert(삽입) > Drawing(그림)으로 버튼 이미지 추가
 * 4. 버튼 클릭 → 오른쪽 상단 점 세 개(⋮) > Assign script(스크립트 할당)
 *    → 함수명 "recallFnG" 입력 후 확인
 * ============================================================
 */

var SUMMARY_TAB = "Summary";
var CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata";

function recallFnG() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(SUMMARY_TAB);

  if (!sheet) {
    SpreadsheetApp.getUi().alert("'" + SUMMARY_TAB + "' 탭을 찾을 수 없습니다.");
    return;
  }

  // 1. CNN F&G 현재값 조회
  var fngValue = null;
  var fngSource = "";

  try {
    var options = {
      "method": "get",
      "headers": {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://edition.cnn.com/",
        "Origin": "https://edition.cnn.com"
      },
      "muteHttpExceptions": true
    };
    var response = UrlFetchApp.fetch(CNN_URL, options);
    var responseCode = response.getResponseCode();
    if (responseCode === 200) {
      var data = JSON.parse(response.getContentText());
      fngValue = Math.round(data["fear_and_greed"]["score"]);
      fngSource = "CNN";
    } else {
      throw new Error("HTTP " + responseCode);
    }
  } catch (e) {
    SpreadsheetApp.getUi().alert(
      "CNN F&G 조회 실패: " + e.toString() + "\n\n" +
      "스케줄러를 수동으로 재실행해 주세요.\n" +
      "터미널: python scheduler_market_close.py"
    );
    return;
  }

  // 2. F&G 레이블 계산
  var label = getFngLabel(fngValue);
  var now = new Date();
  var nowStr = Utilities.formatDate(now, "Asia/Seoul", "yyyy-MM-dd HH:mm") + " KST";

  // 3. Summary 탭 데이터 읽기
  var allData = sheet.getDataRange().getValues();
  var numRows = allData.length;
  var numCols = allData[0].length;

  // 파라미터 행 파싱 (3번 행: "최적 F&G 파라미터: Extreme Fear ≤ {fear_max} | Extreme Greed ≥ {greed_min}")
  var fearMax = 25;    // 기본값
  var greedMin = 75;   // 기본값
  for (var r = 0; r < Math.min(5, numRows); r++) {
    var cellText = String(allData[r][0]);
    if (cellText.indexOf("Extreme Fear") >= 0) {
      var fearMatch = cellText.match(/Extreme Fear\s*[≤<=]+\s*(\d+)/);
      var greedMatch = cellText.match(/Extreme Greed\s*[≥>=]+\s*(\d+)/);
      if (fearMatch)  fearMax  = parseInt(fearMatch[1]);
      if (greedMatch) greedMin = parseInt(greedMatch[1]);
      break;
    }
  }

  // 4. 액션 헤더 행 찾기 (종목 | 전략명 | 현재상태 | ... | F&G | ...)
  var headerRow = -1;
  var colTicker = 0, colState = 2, colFng = 6, colBuyPx = 8, colSellPx = 9, colAction = 10;
  for (var r = 0; r < numRows; r++) {
    if (String(allData[r][0]) === "종목" && String(allData[r][6]).indexOf("F&G") >= 0) {
      headerRow = r;
      // 열 인덱스 동적 확인
      for (var c = 0; c < allData[r].length; c++) {
        var h = String(allData[r][c]);
        if (h === "종목")              colTicker  = c;
        if (h === "현재상태")          colState   = c;
        if (h.indexOf("F&G") >= 0)    colFng     = c;
        if (h.indexOf("BUY") >= 0)    colBuyPx   = c;
        if (h.indexOf("SELL") >= 0)   colSellPx  = c;
        if (h.indexOf("추천") >= 0)   colAction  = c;
      }
      break;
    }
  }

  if (headerRow < 0) {
    SpreadsheetApp.getUi().alert("Summary 탭에서 액션 헤더 행을 찾지 못했습니다.");
    return;
  }

  // 5. TQQQ / SOXL 데이터 행 및 📌 행 업데이트
  var updatedRows = [];
  for (var r = headerRow + 1; r < numRows; r++) {
    var ticker = String(allData[r][colTicker]);
    if (ticker === "TQQQ" || ticker === "SOXL") {
      var currentState = String(allData[r][colState]);
      var buyPx  = parseFloat(allData[r][colBuyPx])  || 0;
      var sellPx = parseFloat(allData[r][colSellPx]) || 0;

      // F&G 셀 업데이트
      sheet.getRange(r + 1, colFng + 1).setValue(fngValue);
      sheet.getRange(r + 1, colFng + 1).setBackground("#c8e6c9");  // 초록: 정상

      // next_action 재계산
      var nextAction = buildNextAction(fngValue, fearMax, greedMin, currentState, buyPx, sellPx, fngSource);
      sheet.getRange(r + 1, colAction + 1).setValue(nextAction);

      // 📌 행도 업데이트 (다음 행)
      if (r + 1 < numRows) {
        var nextRowVal = String(allData[r + 1][0]);
        if (nextRowVal.indexOf("📌") >= 0) {
          sheet.getRange(r + 2, 1).setValue("📌 " + nextAction);
          r++;  // 📌 행 건너뜀
        }
      }

      updatedRows.push(ticker);
    }
  }

  // 6. F&G 오류 배너 행 클리어 (빨간 배너 → 초록 성공 메시지로 교체)
  for (var r = 0; r < numRows; r++) {
    var cellText = String(allData[r][0]);
    if (cellText.indexOf("[F&G 오류]") >= 0 || cellText.indexOf("FNG_ERROR") >= 0) {
      sheet.getRange(r + 1, 1).setValue(
        "✅ [F&G Recall 완료] " + fngValue + "/100  " + label + "  [" + fngSource + "]  @ " + nowStr
      );
      sheet.getRange(r + 1, 1, 1, numCols).setBackground("#c8e6c9");  // 초록
      sheet.getRange(r + 1, 1).setFontColor("#1b5e20");
      break;
    }
  }

  SpreadsheetApp.getUi().alert(
    "✅ F&G Recall 완료\n" +
    "Fear & Greed: " + fngValue + "/100  " + label + "  [" + fngSource + "]\n" +
    "업데이트 시각: " + nowStr + "\n\n" +
    "업데이트된 종목: " + updatedRows.join(", ")
  );
}


function buildNextAction(fngValue, fearMax, greedMin, currentState, buyPx, sellPx, source) {
  var isHolding = currentState.indexOf("주식") >= 0;
  var fngNote = " [F&G Recall:" + source + "]";

  if (!isHolding) {
    // 현금 보유 → 매수 검토
    if (fngValue >= greedMin) {
      var msg = "⛔ 매수 보류 (F&G=" + fngValue + " ≥ " + greedMin + "). F&G가 " + (greedMin - 1) + " 이하로 내려오면 LOC 매수";
      if (buyPx > 0) msg += " 기준가 $" + buyPx.toFixed(2);
      return msg + fngNote;
    } else {
      if (buyPx > 0) {
        return "다음 장 시작 전에  LOC 매수 주문을  $" + buyPx.toFixed(2) + "  에 걸어주세요." + fngNote;
      }
      return "매수 기준가 계산불가" + fngNote;
    }
  } else {
    // 주식 보유 → 매도 검토
    if (fngValue <= fearMax) {
      var msg = "⛔ 매도 보류 (F&G=" + fngValue + " ≤ " + fearMax + "). F&G가 " + (fearMax + 1) + " 이상으로 올라오면 LOC 매도";
      if (sellPx > 0) msg += " 기준가 $" + sellPx.toFixed(2);
      return msg + fngNote;
    } else {
      if (sellPx > 0) {
        return "다음 장 시작 전에  LOC 매도 주문을  $" + sellPx.toFixed(2) + "  에 걸어주세요." + fngNote;
      }
      return "매도 기준가 계산불가" + fngNote;
    }
  }
}


function getFngLabel(value) {
  if (value <= 24)  return "Extreme Fear (극도 공포)";
  if (value <= 44)  return "Fear (공포)";
  if (value <= 54)  return "Neutral (중립)";
  if (value <= 74)  return "Greed (탐욕)";
  return "Extreme Greed (극도 탐욕)";
}
