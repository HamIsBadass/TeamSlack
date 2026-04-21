#!/usr/bin/env python3
"""
Quick orchestration channel threading test.
Run: python3 test_orchestration_demo.py
"""

import sys
import os
from pathlib import Path

# Setup paths - match the pattern used in socket_mode_runner.py
ROOT_DIR = Path(__file__).resolve().parent  # /TeamSlack
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Load env from repo root
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT_DIR / ".env")
except:
    pass

# Now try importing SlackHandler
try:
    from apps.slack_bot.slack_handler import SlackHandler
except ImportError as e:
    print(f"Import error: {e}")
    print(f"Attempting alternative import path...")
    # Try direct path
    sys.path.insert(0, str(ROOT_DIR / "apps" / "slack-bot"))
    sys.path.insert(0, str(ROOT_DIR / "services"))
    from slack_handler import SlackHandler

def check_env():
    """Check required environment variables."""
    required = ["SLACK_BOT_TOKEN", "SLACK_ORCHESTRA_CHANNEL_ID"]
    missing = [var for var in required if not os.getenv(var)]
    
    if missing:
        print("❌ 환경변수 설정 필요:")
        for var in missing:
            print(f"   export {var}=\"...\"")
        return False
    print("✅ 환경변수 확인됨\n")
    return True

def test_dms_to_thread():
    """Test: DM → root message in orchestration channel → status updates in thread"""
    print("=" * 60)
    print("테스트 1: DM → 루트 메시지 → 스레드 업데이트")
    print("=" * 60)
    
    handler = SlackHandler()
    
    # Simulate user DM
    print("\n[1] 사용자가 DM 전송...")
    result = handler.handle_dm_message(
        user_id="U123456789",
        text="회의 정리 부탁드립니다"
    )
    
    request_id = result["request_id"]
    print(f"✓ 요청 생성됨")
    print(f"  - request_id: {request_id[:8]}...")
    print(f"  - status: {result['status']}")
    print(f"  - trace_id: {result['trace_id'][:8]}...")
    
    # Check Slack context was attached
    req = handler.orchestrator.get_request_status(request_id)
    if req.get("slack_thread_ts"):
        print(f"✓ 오케스트레이션 채널에 루트 메시지 생성됨")
        print(f"  - thread_ts: {req.get('slack_thread_ts')}")
    else:
        print(f"⚠️  thread_ts 저장 안 됨 (SLACK_BOT_TOKEN 확인)")
    
    # Simulate status updates
    statuses = ["PARSING", "MEETING_DONE", "JIRA_DRAFTED"]
    print(f"\n[2] 상태 업데이트 시뮬레이션...")
    for status in statuses:
        success = handler.orchestrator.update_status(request_id, status)
        print(f"✓ {status}: {success}")
    
    # Final state
    final_req = handler.orchestrator.get_request_status(request_id)
    print(f"\n✅ 최종 상태:")
    print(f"  - status: {final_req['status']}")
    print(f"  - current_step: {final_req['current_step']}")
    print(f"  - logs: {len(final_req['logs'])} 항목")

def test_approval_flow():
    """Test: WAITING_APPROVAL → approval message in thread"""
    print("\n\n" + "=" * 60)
    print("테스트 2: 승인 요청 흐름")
    print("=" * 60)
    
    handler = SlackHandler()
    
    # Create request
    print("\n[1] 새로운 요청 생성...")
    result = handler.handle_dm_message(
        user_id="U987654321",
        text="다음 주 팀 회의 자료 정리 필요"
    )
    request_id = result["request_id"]
    print(f"✓ 요청 ID: {request_id[:8]}...")
    
    # Progress through states
    print(f"\n[2] 워크플로우 진행...")
    states = ["PARSING", "MEETING_DONE", "JIRA_DRAFTED", "REVIEW_DONE"]
    for state in states:
        handler.orchestrator.update_status(request_id, state)
        print(f"✓ {state}")
    
    # Trigger approval request
    print(f"\n[3] 승인 요청 발송...")
    success = handler.orchestrator.update_status(request_id, "WAITING_APPROVAL")
    print(f"✓ 승인 요청 메시지가 스레드에 포스트됨: {success}")
    
    # Check request details
    req = handler.orchestrator.get_request_status(request_id)
    print(f"\n✅ 요청 상태:")
    print(f"  - status: {req['status']}")
    print(f"  - raw_text: {req['raw_text'][:30]}...")
    
def test_approval_action():
    """Test: handle button click (approve/reject/cancel)"""
    print("\n\n" + "=" * 60)
    print("테스트 3: 승인 액션 처리 (버튼 클릭)")
    print("=" * 60)
    
    handler = SlackHandler()
    
    # Create and advance to approval state
    print("\n[1] 승인 대기 상태의 요청 생성...")
    result = handler.handle_dm_message(
        user_id="U111222333",
        text="승인 테스트 요청"
    )
    request_id = result["request_id"]
    
    for state in ["PARSING", "MEETING_DONE", "JIRA_DRAFTED", "REVIEW_DONE", "WAITING_APPROVAL"]:
        handler.orchestrator.update_status(request_id, state)
    print(f"✓ 요청 상태: WAITING_APPROVAL")
    
    # Test approval
    print(f"\n[2] [승인] 버튼 클릭 시뮬레이션...")
    result = handler.handle_button_action(
        action_type="approve",
        user_id="U999999999",
        payload={"request_id": request_id}
    )
    print(f"✓ 결과: {result['result']}")
    
    # Check final state
    req = handler.orchestrator.get_request_status(request_id)
    print(f"\n✅ 최종 상태: {req['status']}")
    print(f"  - approvals: {len(req['approvals'])} 건")

def test_full_lifecycle():
    """Test: Complete request lifecycle"""
    print("\n\n" + "=" * 60)
    print("테스트 4: 전체 라이프사이클")
    print("=" * 60)
    
    handler = SlackHandler()
    
    print("\n[1] 새로운 요청 생성...")
    result = handler.handle_dm_message(
        user_id="U555666777",
        text="전체 라이프사이클 테스트"
    )
    request_id = result["request_id"]
    print(f"✓ 요청 생성: {request_id[:8]}...")
    
    # Full state progression
    print(f"\n[2] 전체 상태 전이...")
    states = [
        "PARSING",
        "MEETING_DONE", 
        "JIRA_DRAFTED",
        "REVIEW_DONE",
        "WAITING_APPROVAL",
        "APPROVED",
        "DONE"
    ]
    
    for i, state in enumerate(states, 1):
        success = handler.orchestrator.update_status(request_id, state)
        print(f"{i}. {state:20} {'✓' if success else '✗'}")
    
    # Final report
    req = handler.orchestrator.get_request_status(request_id)
    print(f"\n✅ 라이프사이클 완료")
    print(f"  - 최종 상태: {req['status']}")
    print(f"  - 총 로그: {len(req['logs'])} 항목")
    print(f"  - 총 스텝: {len(req['steps'])} 항목")
    print(f"  - 스레드: {req.get('slack_thread_ts', 'N/A')}")

def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("오케스트레이션 채널 스레드 테스트")
    print("=" * 60)
    
    # Check environment
    if not check_env():
        print("\n💡 팁: 환경변수를 설정한 후 실행하세요")
        print("   export SLACK_BOT_TOKEN=\"xoxb-...\"")
        print("   export SLACK_ORCHESTRA_CHANNEL_ID=\"C...\"")
        print("   python3 test_orchestration_demo.py")
        return
    
    try:
        test_dms_to_thread()
        test_approval_flow()
        test_approval_action()
        test_full_lifecycle()
        
        print("\n\n" + "=" * 60)
        print("✅ 모든 테스트 완료!")
        print("=" * 60)
        print("\n📌 다음 단계:")
        print("   1. 위 출력값 확인")
        print("   2. Slack 앱에서 오케스트레이션 채널 확인")
        print("   3. 스레드에 메시지가 보이는지 확인")
        print("   4. socket_mode_runner.py로 실시간 테스트")
        print()
        
    except Exception as e:
        print(f"\n❌ 에러 발생: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
