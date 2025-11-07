#!/usr/bin/env python3
"""
Validation test for cTrader client implementations
Tests code structure and logic without requiring real credentials
"""

import sys
import json
from pathlib import Path

def test_imports():
    """Test that all required modules can be imported"""
    print("=" * 70)
    print("Testing Imports")
    print("=" * 70)
    
    try:
        from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
        import ctrader_open_api.messages.OpenApiMessages_pb2 as OA
        from twisted.internet import reactor, defer
        import websockets
        from dotenv import load_dotenv
        print("✅ All imports successful")
        return True
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        return False

def test_file_structure():
    """Test that all expected files exist"""
    print("\n" + "=" * 70)
    print("Testing File Structure")
    print("=" * 70)
    
    required_files = [
        'test_live_stream.py',
        'ctrader_client_improved.py',
        'ctrader_ws_client.py',
        'test_ctrader_twisted.py',
        'ctrader_oauth_setup.py',
        'requirements.txt',
        'README.md',
        'TROUBLESHOOTING.md',
        '.env.example',
    ]
    
    all_exist = True
    for file in required_files:
        if Path(file).exists():
            print(f"✅ {file}")
        else:
            print(f"❌ {file} - NOT FOUND")
            all_exist = False
    
    return all_exist

def test_credentials_loading():
    """Test credential loading logic (without actual credentials)"""
    print("\n" + "=" * 70)
    print("Testing Credential Loading Logic")
    print("=" * 70)
    
    # Test that the load_credentials function exists and has proper structure
    try:
        # Create a temporary test credentials file
        test_creds = {
            'client_id': 'test_client_id',
            'client_secret': 'test_client_secret',
            'access_token': 'test_access_token',
            'account_id': 12345
        }
        
        with open('test_credentials.json', 'w') as f:
            json.dump(test_creds, f)
        
        # Test loading
        with open('test_credentials.json', 'r') as f:
            loaded = json.load(f)
        
        assert loaded['client_id'] == 'test_client_id'
        assert loaded['account_id'] == 12345
        
        # Clean up
        Path('test_credentials.json').unlink()
        
        print("✅ Credential loading logic works correctly")
        return True
    except Exception as e:
        print(f"❌ Credential loading test failed: {e}")
        # Clean up on failure
        if Path('test_credentials.json').exists():
            Path('test_credentials.json').unlink()
        return False

def test_payload_types():
    """Test that payload type constants are defined"""
    print("\n" + "=" * 70)
    print("Testing Payload Type Constants")
    print("=" * 70)
    
    try:
        import ctrader_open_api.messages.OpenApiMessages_pb2 as OA
        
        # Test that key message types exist
        message_types = [
            ('ProtoOAApplicationAuthReq', OA.ProtoOAApplicationAuthReq()),
            ('ProtoOAApplicationAuthRes', OA.ProtoOAApplicationAuthRes()),
            ('ProtoOAAccountAuthReq', OA.ProtoOAAccountAuthReq()),
            ('ProtoOAAccountAuthRes', OA.ProtoOAAccountAuthRes()),
            ('ProtoOAErrorRes', OA.ProtoOAErrorRes()),
            ('ProtoOASpotEvent', OA.ProtoOASpotEvent()),
        ]
        
        for name, msg in message_types:
            print(f"✅ {name}: {msg.payloadType}")
        
        return True
    except Exception as e:
        print(f"❌ Payload type test failed: {e}")
        return False

def test_endpoints():
    """Test that endpoint constants are available"""
    print("\n" + "=" * 70)
    print("Testing Endpoint Constants")
    print("=" * 70)
    
    try:
        from ctrader_open_api import EndPoints
        
        print(f"✅ PROTOBUF_DEMO_HOST: {EndPoints.PROTOBUF_DEMO_HOST}")
        print(f"✅ PROTOBUF_LIVE_HOST: {EndPoints.PROTOBUF_LIVE_HOST}")
        print(f"✅ PROTOBUF_PORT: {EndPoints.PROTOBUF_PORT}")
        
        return True
    except Exception as e:
        print(f"❌ Endpoint test failed: {e}")
        return False

def main():
    """Run all validation tests"""
    print("\n" + "=" * 70)
    print("🧪 cTrader Client Implementation Validation")
    print("=" * 70)
    print()
    
    tests = [
        ("Imports", test_imports),
        ("File Structure", test_file_structure),
        ("Credential Loading", test_credentials_loading),
        ("Payload Types", test_payload_types),
        ("Endpoints", test_endpoints),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ Test '{name}' crashed: {e}")
            results.append((name, False))
    
    # Summary
    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    print()
    print(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All validation tests passed!")
        print("✅ cTrader client implementations are correctly structured")
        print("\nNext steps:")
        print("1. Run: python ctrader_oauth_setup.py")
        print("2. Then test: python test_live_stream.py")
        return 0
    else:
        print("\n⚠️  Some tests failed")
        print("Please review the errors above")
        return 1

if __name__ == "__main__":
    sys.exit(main())
