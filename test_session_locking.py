#!/usr/bin/env python3
"""
Test script for session locking feature.
Verifies that only one trading session can run during market hours.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_session_locking():
    """Test session lock acquire and release."""
    print("\n[TEST] Session Locking Feature")
    print("-" * 70)
    
    from app.core.storage import storage
    
    # Clean up any existing locks first
    storage.release_session_lock()
    
    # Test 1: Acquire first lock
    print("\n1. Acquiring first session lock (PAPER mode)...")
    success1, msg1 = storage.acquire_session_lock(trading_mode="PAPER")
    assert success1, f"Failed to acquire first lock: {msg1}"
    print(f"   [OK] {msg1}")
    
    # Test 2: Try to acquire second lock (should fail)
    print("\n2. Attempting to acquire second lock (should fail)...")
    success2, msg2 = storage.acquire_session_lock(trading_mode="LIVE")
    assert not success2, "Should not allow second session"
    print(f"   [OK] Correctly blocked: {msg2}")
    
    # Test 3: Check if session is active
    print("\n3. Checking if session is active...")
    is_active = storage.is_session_active()
    assert is_active, "Session should be active"
    print(f"   [OK] Session is active: {is_active}")
    
    # Test 4: Release lock
    print("\n4. Releasing session lock...")
    storage.release_session_lock()
    print(f"   [OK] Lock released")
    
    # Test 5: Verify session is inactive
    print("\n5. Verifying session is no longer active...")
    is_active = storage.is_session_active()
    assert not is_active, "Session should be inactive after release"
    print(f"   [OK] Session is inactive")
    
    # Test 6: Acquire new lock after release
    print("\n6. Re-acquiring lock after release...")
    success3, msg3 = storage.acquire_session_lock(trading_mode="LIVE")
    assert success3, f"Failed to re-acquire lock: {msg3}"
    print(f"   [OK] {msg3}")
    
    # Clean up
    storage.release_session_lock()
    
    print("\n" + "=" * 70)
    print("[SUCCESS] All session locking tests passed!")
    print("=" * 70)
    print("\nHow it works:")
    print("-" * 70)
    print("1. When you run 'python -m app run --live' during market hours")
    print("2. It tries to acquire a session lock for today")
    print("3. If successful: Trading loop starts")
    print("4. If failed (lock exists): Monitoring window is shown instead")
    print("5. Lock is automatically released at 3:30 PM or on shutdown")
    print("\nBenefit:")
    print("- Prevents accidental duplicate trading on multiple devices")
    print("- Shows monitoring window instead if session already active")
    print("- Automatic cleanup at market close (3:30 PM)")
    print("-" * 70)
    return 0

if __name__ == "__main__":
    try:
        sys.exit(test_session_locking())
    except Exception as e:
        print(f"\n[FAILED] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
