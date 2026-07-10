#!/usr/bin/env python3
"""
Scenario Simulator (통합 테스트 시뮬레이터)

이 도구는 실제 하드웨어나 센서가 없는 환경에서
로봇의 배터리, 장애물, 비상 정지 상태를 가상으로 만들어 전달합니다.

사용 방법:
1. 한쪽 터미널에서 mission_manager.py를 실행합니다.
2. 다른 터미널에서 이 스크립트를 실행하여 상황을 조작합니다.
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String
from sensor_msgs.msg import BatteryState

class ScenarioSimulator(Node):
    def __init__(self):
        super().__init__('scenario_simulator')

        # 신호 발행을 위한 Publisher 설정
        self.battery_pub = self.create_publisher(BatteryState, '/battery_state', 10)
        self.estop_pub = self.create_publisher(Bool, '/emergency_stop', 10)
        self.obstacle_pub = self.create_publisher(String, '/obstacle_status', 10)

        print("\n" + "="*50)
        print("   물류 자율주행 통합 테스트 시뮬레이터")
        print("="*50)

    def send_battery(self, percentage):
        msg = BatteryState()
        msg.percentage = float(percentage) / 100.0
        self.battery_pub.publish(msg)
        print(f"[전송] 배터리 잔량: {percentage}%")

    def send_estop(self, state: bool):
        msg = Bool()
        msg.data = state
        self.estop_pub.publish(msg)
        print(f"[전송] 비상 정지(ESTOP): {'ON' if state else 'OFF'}")

    def send_obstacle(self, status: str):
        msg = String()
        msg.data = status
        self.obstacle_pub.publish(msg)
        print(f"[전송] 장애물 상태: {status}")

def print_menu():
    print("\n--- 상황 선택 (번호 입력) ---")
    print("[1] 배터리 부족 (15%)      [2] 배터리 정상 (100%)")
    print("[3] 장애물 발생 (정적)     [4] 장애물 발생 (동적)")
    print("[5] 장애물 해제 (None)     [6] 비상 정지 (ON)")
    print("[7] 비상 정지 (OFF)        [q] 종료")
    print("-" * 30)

def main():
    rclpy.init()
    sim = ScenarioSimulator()

    try:
        while True:
            print_menu()
            choice = input("입력: ").strip().lower()

            if choice == '1':
                sim.send_battery(15)
            elif choice == '2':
                sim.send_battery(100)
            elif choice == '3':
                sim.send_obstacle('static')
            elif choice == '4':
                sim.send_obstacle('dynamic')
            elif choice == '5':
                sim.send_obstacle('none')
            elif choice == '6':
                sim.send_estop(True)
            elif choice == '7':
                sim.send_estop(False)
            elif choice == 'q':
                break
            else:
                print("잘못된 입력입니다.")

    except KeyboardInterrupt:
        pass
    finally:
        sim.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
