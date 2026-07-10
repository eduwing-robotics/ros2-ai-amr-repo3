-- SQL dump generated using DBML (dbml.dbdiagram.io)
-- Database: PostgreSQL
-- Generated at: 2026-06-24T05:07:38.925Z

CREATE TABLE "locations" (
  "id" text PRIMARY KEY,
  "type" text NOT NULL,
  "status" text NOT NULL,
  "parent_id" text,
  "approach_id" text,
  "x" float8,
  "y" float8,
  "yaw" float8,
  "marker_id" integer
);

CREATE TABLE "robots" (
  "id" text PRIMARY KEY,
  "domain_id" integer NOT NULL,
  "status" text NOT NULL,
  "battery_level" float8,
  "location_id" text,
  "active_task_id" bigint,
  "last_seen_at" timestamptz
);

CREATE TABLE "items" (
  "id" text PRIMARY KEY
);

CREATE TABLE "inventory" (
  "item_id" text NOT NULL,
  "location_id" text NOT NULL,
  "quantity" integer NOT NULL DEFAULT 0,
  "updated_at" timestamptz,
  PRIMARY KEY ("item_id", "location_id")
);

CREATE TABLE "tasks" (
  "id" bigint PRIMARY KEY,
  "task_type" text NOT NULL,
  "status" text NOT NULL,
  "priority" integer NOT NULL DEFAULT 0,
  "robot_id" text,
  "item_id" text,
  "quantity" integer NOT NULL DEFAULT 1,
  "from_location_id" text,
  "to_location_id" text,
  "error_reason" text,
  "created_at" timestamptz,
  "started_at" timestamptz,
  "finished_at" timestamptz
);

CREATE TABLE "reservations" (
  "id" bigint PRIMARY KEY,
  "type" text NOT NULL,
  "status" text NOT NULL,
  "task_id" bigint NOT NULL,
  "robot_id" text,
  "location_id" text,
  "item_id" text,
  "expires_at" timestamptz,
  "released_at" timestamptz
);

CREATE TABLE "commands" (
  "id" bigint PRIMARY KEY,
  "task_id" bigint,
  "robot_id" text,
  "sequence_no" integer NOT NULL DEFAULT 1,
  "command_type" text NOT NULL,
  "target_system" text NOT NULL,
  "status" text NOT NULL,
  "location_id" text,
  "required_evidence_type" text,
  "idempotency_key" text UNIQUE NOT NULL,
  "request_json" jsonb,
  "response_json" jsonb,
  "deadline_at" timestamptz,
  "created_at" timestamptz,
  "updated_at" timestamptz
);

CREATE TABLE "evidence_events" (
  "id" bigint PRIMARY KEY,
  "event_type" text NOT NULL,
  "source" text NOT NULL,
  "robot_id" text,
  "task_id" bigint,
  "command_id" bigint,
  "location_id" text,
  "confidence" float8,
  "severity" text NOT NULL DEFAULT 'INFO',
  "trusted" boolean NOT NULL DEFAULT false,
  "image_uri" text,
  "data_json" jsonb,
  "observed_at" timestamptz
);

CREATE TABLE "safety_stops" (
  "id" bigint PRIMARY KEY,
  "status" text NOT NULL,
  "robot_id" text,
  "task_id" bigint,
  "detected_evidence_id" bigint,
  "stop_command_id" bigint,
  "clear_evidence_id" bigint,
  "opened_at" timestamptz,
  "closed_at" timestamptz
);

CREATE TABLE "task_logs" (
  "id" bigint PRIMARY KEY,
  "task_id" bigint NOT NULL,
  "robot_id" text,
  "item_id" text,
  "task_type" text NOT NULL,
  "result" text NOT NULL,
  "quantity" integer,
  "from_location_id" text,
  "to_location_id" text,
  "started_at" timestamptz,
  "finished_at" timestamptz,
  "fail_reason" text,
  "summary" text,
  "snapshot_json" jsonb,
  "logged_at" timestamptz NOT NULL
);

CREATE TABLE "item_change_logs" (
  "id" bigint PRIMARY KEY,
  "item_id" text NOT NULL,
  "location_id" text,
  "task_id" bigint,
  "event_type" text NOT NULL,
  "quantity_change" integer NOT NULL,
  "quantity_before" integer,
  "quantity_after" integer,
  "reason" text,
  "changed_at" timestamptz NOT NULL
);

CREATE INDEX ON "locations" ("type");

CREATE INDEX ON "locations" ("status");

CREATE INDEX ON "locations" ("parent_id");

CREATE INDEX ON "locations" ("approach_id");

CREATE INDEX ON "robots" ("domain_id");

CREATE INDEX ON "robots" ("status");

CREATE INDEX ON "robots" ("location_id");

CREATE INDEX ON "robots" ("active_task_id");

CREATE INDEX ON "robots" ("last_seen_at");

CREATE INDEX ON "inventory" ("location_id");

CREATE INDEX ON "tasks" ("task_type");

CREATE INDEX ON "tasks" ("status");

CREATE INDEX ON "tasks" ("robot_id");

CREATE INDEX ON "tasks" ("item_id");

CREATE INDEX ON "tasks" ("from_location_id");

CREATE INDEX ON "tasks" ("to_location_id");

CREATE INDEX ON "tasks" ("created_at");

CREATE INDEX ON "reservations" ("status");

CREATE INDEX ON "reservations" ("task_id");

CREATE INDEX ON "reservations" ("robot_id");

CREATE INDEX ON "reservations" ("location_id");

CREATE INDEX ON "reservations" ("item_id");

CREATE INDEX ON "reservations" ("expires_at");

CREATE INDEX ON "commands" ("task_id");

CREATE INDEX ON "commands" ("robot_id");

CREATE INDEX ON "commands" ("status");

CREATE INDEX ON "commands" ("location_id");

CREATE INDEX ON "commands" ("required_evidence_type");

CREATE INDEX ON "commands" ("created_at");

CREATE UNIQUE INDEX ON "commands" ("task_id", "sequence_no");

CREATE INDEX ON "evidence_events" ("event_type");

CREATE INDEX ON "evidence_events" ("source");

CREATE INDEX ON "evidence_events" ("robot_id");

CREATE INDEX ON "evidence_events" ("task_id");

CREATE INDEX ON "evidence_events" ("command_id");

CREATE INDEX ON "evidence_events" ("location_id");

CREATE INDEX ON "evidence_events" ("trusted");

CREATE INDEX ON "evidence_events" ("observed_at");

CREATE INDEX ON "safety_stops" ("status");

CREATE INDEX ON "safety_stops" ("robot_id");

CREATE INDEX ON "safety_stops" ("task_id");

CREATE INDEX ON "safety_stops" ("detected_evidence_id");

CREATE INDEX ON "safety_stops" ("opened_at");

CREATE INDEX ON "task_logs" ("task_id");

CREATE INDEX ON "task_logs" ("robot_id");

CREATE INDEX ON "task_logs" ("item_id");

CREATE INDEX ON "task_logs" ("result");

CREATE INDEX ON "task_logs" ("task_type");

CREATE INDEX ON "task_logs" ("finished_at");

CREATE INDEX ON "task_logs" ("logged_at");

CREATE INDEX ON "item_change_logs" ("item_id");

CREATE INDEX ON "item_change_logs" ("location_id");

CREATE INDEX ON "item_change_logs" ("task_id");

CREATE INDEX ON "item_change_logs" ("event_type");

CREATE INDEX ON "item_change_logs" ("changed_at");

COMMENT ON COLUMN "locations"."id" IS 'INBOUND_01/STORAGE_A_01/OUTBOUND_01/CHARGE_01';

COMMENT ON COLUMN "locations"."type" IS 'AREA/WAYPOINT/SLOT/CHARGE';

COMMENT ON COLUMN "locations"."status" IS 'AVAILABLE/RESERVED/OCCUPIED/BLOCKED/UNKNOWN';

COMMENT ON COLUMN "locations"."marker_id" IS 'ArUco marker id, nullable';

COMMENT ON COLUMN "robots"."id" IS 'tb3_1/tb3_2';

COMMENT ON COLUMN "robots"."domain_id" IS 'ROS_DOMAIN_ID for this robot';

COMMENT ON COLUMN "robots"."status" IS 'IDLE/RESERVED/MOVING/DOCKING/LIFTING/PAUSED/ERROR/OFFLINE/CHARGING';

COMMENT ON COLUMN "items"."id" IS 'BOLT_M3/MOTOR_A/SENSOR_KIT; display value is merged into id for MVP';

COMMENT ON COLUMN "tasks"."task_type" IS 'INBOUND/OUTBOUND/MOVE/RECOVERY/CHARGING';

COMMENT ON COLUMN "tasks"."status" IS 'PENDING/RUNNING/PAUSED/COMPLETED/FAILED/CANCELLED/NEEDS_REVIEW';

COMMENT ON COLUMN "reservations"."type" IS 'ROBOT/LOCATION/ITEM';

COMMENT ON COLUMN "reservations"."status" IS 'ACTIVE/RELEASED/EXPIRED/CANCELLED';

COMMENT ON COLUMN "commands"."sequence_no" IS 'command order inside a task';

COMMENT ON COLUMN "commands"."command_type" IS 'NAV_GOAL/PICK_UP/DROP_OFF/STOP/RESUME/START_CHARGING/STOP_CHARGING';

COMMENT ON COLUMN "commands"."target_system" IS 'NAV_SERVER/AI_SERVER/ROBOT_BRIDGE';

COMMENT ON COLUMN "commands"."status" IS 'PENDING/SENT/ACKED/SUCCEEDED/FAILED/TIMEOUT/CANCELLED';

COMMENT ON COLUMN "commands"."location_id" IS 'goal or work location for API request composition';

COMMENT ON COLUMN "commands"."required_evidence_type" IS 'NAV_REACHED/ITEM_PICKED/ITEM_PLACED/HUMAN_CLEAR';

COMMENT ON COLUMN "commands"."request_json" IS 'actual API request snapshot after composing from task/location/command fields';

COMMENT ON COLUMN "evidence_events"."event_type" IS 'NAV_REACHED/ARUCO_DETECTED/LOAD_DETECTED/ITEM_PICKED/ITEM_PLACED/SLOT_CONFIRMED/HUMAN_DETECTED/HUMAN_CLEAR/ERROR/STATUS';

COMMENT ON COLUMN "evidence_events"."source" IS 'global_cam_01/tb3_1_picam/nav_server/operator';

COMMENT ON COLUMN "evidence_events"."severity" IS 'INFO/WARN/ERROR/SAFETY';

COMMENT ON COLUMN "safety_stops"."status" IS 'OPEN/STOP_SENT/STOPPED/CLEAR_PENDING/RESUME_ALLOWED/CLOSED';

COMMENT ON COLUMN "task_logs"."task_type" IS 'task_type copied from tasks';

COMMENT ON COLUMN "task_logs"."result" IS 'SUCCESS/FAILURE/CANCELLED/NEEDS_REVIEW';

COMMENT ON COLUMN "task_logs"."snapshot_json" IS 'final query/evidence summary snapshot for audit';

COMMENT ON COLUMN "item_change_logs"."event_type" IS 'INBOUND/OUTBOUND/MOVE/ADJUST/CORRECTION/RESERVED/RELEASED';

ALTER TABLE "locations" ADD FOREIGN KEY ("parent_id") REFERENCES "locations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "locations" ADD FOREIGN KEY ("approach_id") REFERENCES "locations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "robots" ADD FOREIGN KEY ("location_id") REFERENCES "locations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "inventory" ADD FOREIGN KEY ("item_id") REFERENCES "items" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "inventory" ADD FOREIGN KEY ("location_id") REFERENCES "locations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "tasks" ADD FOREIGN KEY ("robot_id") REFERENCES "robots" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "tasks" ADD FOREIGN KEY ("item_id") REFERENCES "items" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "tasks" ADD FOREIGN KEY ("from_location_id") REFERENCES "locations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "tasks" ADD FOREIGN KEY ("to_location_id") REFERENCES "locations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "reservations" ADD FOREIGN KEY ("task_id") REFERENCES "tasks" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "reservations" ADD FOREIGN KEY ("robot_id") REFERENCES "robots" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "reservations" ADD FOREIGN KEY ("location_id") REFERENCES "locations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "reservations" ADD FOREIGN KEY ("item_id") REFERENCES "items" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "commands" ADD FOREIGN KEY ("task_id") REFERENCES "tasks" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "commands" ADD FOREIGN KEY ("robot_id") REFERENCES "robots" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "commands" ADD FOREIGN KEY ("location_id") REFERENCES "locations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "evidence_events" ADD FOREIGN KEY ("robot_id") REFERENCES "robots" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "evidence_events" ADD FOREIGN KEY ("task_id") REFERENCES "tasks" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "evidence_events" ADD FOREIGN KEY ("command_id") REFERENCES "commands" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "evidence_events" ADD FOREIGN KEY ("location_id") REFERENCES "locations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "safety_stops" ADD FOREIGN KEY ("robot_id") REFERENCES "robots" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "safety_stops" ADD FOREIGN KEY ("task_id") REFERENCES "tasks" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "safety_stops" ADD FOREIGN KEY ("detected_evidence_id") REFERENCES "evidence_events" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "safety_stops" ADD FOREIGN KEY ("stop_command_id") REFERENCES "commands" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "safety_stops" ADD FOREIGN KEY ("clear_evidence_id") REFERENCES "evidence_events" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "task_logs" ADD FOREIGN KEY ("task_id") REFERENCES "tasks" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "task_logs" ADD FOREIGN KEY ("robot_id") REFERENCES "robots" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "task_logs" ADD FOREIGN KEY ("item_id") REFERENCES "items" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "task_logs" ADD FOREIGN KEY ("from_location_id") REFERENCES "locations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "task_logs" ADD FOREIGN KEY ("to_location_id") REFERENCES "locations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "item_change_logs" ADD FOREIGN KEY ("item_id") REFERENCES "items" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "item_change_logs" ADD FOREIGN KEY ("location_id") REFERENCES "locations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "item_change_logs" ADD FOREIGN KEY ("task_id") REFERENCES "tasks" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "robots" ADD FOREIGN KEY ("active_task_id") REFERENCES "tasks" ("id") DEFERRABLE INITIALLY IMMEDIATE;
