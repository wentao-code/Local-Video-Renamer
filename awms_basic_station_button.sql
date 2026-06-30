/*
 Navicat Premium Data Transfer

 Source Server         : wwt
 Source Server Type    : MySQL
 Source Server Version : 80045
 Source Host           : localhost:3306
 Source Schema         : button

 Target Server Type    : MySQL
 Target Server Version : 80045
 File Encoding         : 65001

 Date: 30/06/2026 16:54:28
*/

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------
-- Table structure for awms_basic_station_button
-- ----------------------------
DROP TABLE IF EXISTS `awms_basic_station_button`;
CREATE TABLE `awms_basic_station_button`  (
  `id` bigint(0) NOT NULL AUTO_INCREMENT COMMENT '主键',
  `station_code` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '工位编号',
  `button_ip` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '按钮IP，对应clients.remoteIp',
  `enabled` tinyint(1) NOT NULL DEFAULT 1 COMMENT '是否启用：1启用 0停用',
  `remark` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '备注',
  `create_time` datetime(0) DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime(0) DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP(0) COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `uk_station_code`(`station_code`) USING BTREE,
  UNIQUE INDEX `uk_button_ip`(`button_ip`) USING BTREE,
  INDEX `idx_enabled`(`enabled`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 2 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '工位与按钮IP映射表' ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of awms_basic_station_button
-- ----------------------------
INSERT INTO `awms_basic_station_button` VALUES (1, '100', '192.168.1.100', 1, '按钮1号', '2026-06-23 20:21:35', '2026-06-29 21:15:07');

-- ----------------------------
-- Table structure for awms_station_button_event
-- ----------------------------
DROP TABLE IF EXISTS `awms_station_button_event`;
CREATE TABLE `awms_station_button_event`  (
  `id` bigint(0) NOT NULL AUTO_INCREMENT COMMENT '主键',
  `mapping_id` bigint(0) NOT NULL COMMENT '映射表ID',
  `station_code` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '工位编号',
  `button_ip` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '按钮IP',
  `event_type` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '事件类型',
  `event_time` datetime(0) NOT NULL COMMENT '事件时间',
  `bridge_running_before` tinyint(1) DEFAULT NULL COMMENT '变化前桥接服务状态',
  `bridge_running_after` tinyint(1) DEFAULT NULL COMMENT '变化后桥接服务状态',
  `button_connected_before` tinyint(1) DEFAULT NULL COMMENT '变化前按钮在线状态',
  `button_connected_after` tinyint(1) DEFAULT NULL COMMENT '变化后按钮在线状态',
  `delivery_pressed_before` tinyint(1) DEFAULT NULL COMMENT '变化前delivery按下状态',
  `delivery_pressed_after` tinyint(1) DEFAULT NULL COMMENT '变化后delivery按下状态',
  `empty_box_pressed_before` tinyint(1) DEFAULT NULL COMMENT '变化前empty box按下状态',
  `empty_box_pressed_after` tinyint(1) DEFAULT NULL COMMENT '变化后empty box按下状态',
  `delivery_count_before` int(0) DEFAULT NULL COMMENT '变化前delivery累计次数',
  `delivery_count_after` int(0) DEFAULT NULL COMMENT '变化后delivery累计次数',
  `delivery_count_delta` int(0) DEFAULT NULL COMMENT '本次delivery增量',
  `empty_box_count_before` int(0) DEFAULT NULL COMMENT '变化前empty box累计次数',
  `empty_box_count_after` int(0) DEFAULT NULL COMMENT '变化后empty box累计次数',
  `empty_box_count_delta` int(0) DEFAULT NULL COMMENT '本次empty box增量',
  `error_code` int(0) DEFAULT NULL COMMENT '错误码',
  `error_message` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '错误信息',
  `raw_payload` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '本次事件对应原始JSON',
  `create_time` datetime(0) DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `idx_mapping_time`(`mapping_id`, `event_time`) USING BTREE,
  INDEX `idx_station_time`(`station_code`, `event_time`) USING BTREE,
  INDEX `idx_event_type`(`event_type`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '按钮事件历史表' ROW_FORMAT = Dynamic;

-- ----------------------------
-- Table structure for awms_station_button_status
-- ----------------------------
DROP TABLE IF EXISTS `awms_station_button_status`;
CREATE TABLE `awms_station_button_status`  (
  `id` bigint(0) NOT NULL AUTO_INCREMENT COMMENT '主键',
  `mapping_id` bigint(0) NOT NULL COMMENT '映射表ID',
  `station_code` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '工位编号',
  `button_ip` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '按钮IP',
  `bridge_running` tinyint(1) DEFAULT NULL COMMENT '桥接服务是否运行，对应data.running',
  `bridge_connected` tinyint(1) DEFAULT NULL COMMENT '桥接服务是否至少连上一个设备，对应data.connected',
  `button_connected` tinyint(1) DEFAULT NULL COMMENT '当前按钮是否在线，对应clients[n].connected',
  `delivery_pressed` tinyint(1) DEFAULT NULL COMMENT 'delivery按钮当前是否按下',
  `empty_box_pressed` tinyint(1) DEFAULT NULL COMMENT 'empty box按钮当前是否按下',
  `delivery_event_count` int(0) NOT NULL DEFAULT 0 COMMENT 'delivery累计次数',
  `empty_box_event_count` int(0) NOT NULL DEFAULT 0 COMMENT 'empty box累计次数',
  `bridge_last_error_code` int(0) DEFAULT NULL COMMENT '桥接服务最近错误码',
  `bridge_last_error_message` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '桥接服务最近错误信息',
  `button_last_error_code` int(0) DEFAULT NULL COMMENT '当前按钮最近错误码',
  `button_last_error_message` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '当前按钮最近错误信息',
  `last_poll_success` tinyint(1) NOT NULL DEFAULT 0 COMMENT '最近一次轮询是否成功',
  `last_poll_time` datetime(0) DEFAULT NULL COMMENT '最近一次轮询时间',
  `last_change_time` datetime(0) DEFAULT NULL COMMENT '最近一次状态变化时间',
  `last_seen_ms` bigint(0) DEFAULT NULL COMMENT '桥接返回的lastSeenMs原值',
  `raw_payload` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '本按钮对应的原始状态JSON',
  `create_time` datetime(0) DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime(0) DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP(0) COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `uk_mapping_id`(`mapping_id`) USING BTREE,
  INDEX `idx_station_code`(`station_code`) USING BTREE,
  INDEX `idx_button_ip`(`button_ip`) USING BTREE,
  INDEX `idx_last_poll_time`(`last_poll_time`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 1 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '按钮当前状态快照表' ROW_FORMAT = Dynamic;

SET FOREIGN_KEY_CHECKS = 1;
