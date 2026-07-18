// 기능 책임: callback 기반 task 단계 타임라인 표현을 검증한다. 비책임: command 실행.
import { expect, test } from "@playwright/test";
import { item, mockMainApi, robot } from "../support/mainApi";

test("callback 기반 Task 단계는 완료·현재·대기를 타임라인으로 표시한다", async ({ page }) => {
  await mockMainApi(page, {
    workOrders: [
      {
        order_id: 343,
        operation: "inbound",
        item_code: item.item_code,
        quantity: 1,
        status: "RUNNING",
        tasks: [
          {
            order_id: 343,
            task_id: 343,
            quantity: 1,
            status: "RUNNING",
            assigned_robot_id: robot.robot_id,
            business_completed: false,
            progress: {
              phase: "RUNNING",
              current_step_index: 1,
              steps: [
                { step_index: 0, kind: "leave_dock", status: "DONE", command_id: "cmd-leave" },
                { step_index: 1, kind: "move_to_point", transfer_action: "load", status: "DISPATCHED", command_id: "cmd-load" },
                { step_index: 2, kind: "move_to_point", transfer_action: "unload", status: "PENDING" },
              ],
            },
          },
        ],
      },
    ],
  });

  await page.goto("/operate/tasks");
  await page.getByRole("button", { name: "펼치기" }).click();

  const timeline = page.getByRole("region", { name: "Task 343 단계 진행 상황" });
  await expect(timeline).toBeVisible();
  await expect(timeline.getByText("완료 1/3")).toBeVisible();
  await expect(timeline.getByText("대기 위치 이탈")).toBeVisible();
  await expect(timeline.getByText("적재 위치 접근·적재")).toBeVisible();
  await expect(timeline.getByText("현재 진행")).toBeVisible();
  await expect(timeline.getByText("Movement callback 기준")).toBeVisible();
});
