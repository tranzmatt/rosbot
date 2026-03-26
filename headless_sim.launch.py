"""
headless_sim.launch.py

Launches TurtleBot4 simulation server-only (no GUI process).
Uses gz sim -s directly so there is no Ogre/Qt GUI process to crash.
The GUI can connect remotely from a laptop via: gz sim -g
"""

import os
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    ExecuteProcess,
    TimerAction,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare
from launch_ros.actions import Node


def generate_launch_description():

    world = LaunchConfiguration("world")
    model = LaunchConfiguration("model")
    namespace = LaunchConfiguration("namespace")

    declare_world = DeclareLaunchArgument(
        "world",
        default_value="warehouse",
        description="Gazebo world name (without .sdf extension)",
    )

    declare_model = DeclareLaunchArgument(
        "model",
        default_value=os.environ.get("TURTLEBOT4_MODEL", "standard"),
        description="TurtleBot4 model: standard or lite",
    )

    declare_namespace = DeclareLaunchArgument(
        "namespace",
        default_value="",
        description="Robot namespace",
    )

    # World SDF path
    world_sdf = PathJoinSubstitution([
        FindPackageShare("turtlebot4_gz_bringup"),
        "worlds",
        [world, ".sdf"],
    ])

    # gz sim server only (-s = server, -r = run immediately, no GUI)
    gz_server = ExecuteProcess(
        cmd=["gz", "sim", "-s", "-r", "-v", "3", world_sdf],
        output="screen",
    )

    # Clock bridge: Gazebo /clock → ROS2 /clock
    # Must start before spawn so controller_manager gets sim time from the start.
    # Without this, gz_ros2_control logs "No clock received" and physics never ticks.
    clock_bridge = TimerAction(
        period=5.0,
        actions=[
            Node(
                package="ros_gz_bridge",
                executable="parameter_bridge",
                name="clock_bridge",
                arguments=["/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock"],
                output="screen",
                parameters=[{"use_sim_time": True}],
            )
        ],
    )

    # Spawn TurtleBot4 into the world (delayed to let server start)
    spawn = TimerAction(
        period=8.0,
        actions=[
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource([
                    PathJoinSubstitution([
                        FindPackageShare("turtlebot4_gz_bringup"),
                        "launch",
                        "turtlebot4_spawn.launch.py",
                    ])
                ]),
                launch_arguments={
                    "model": model,
                    "namespace": namespace,
                }.items(),
            )
        ],
    )

    # ROS-Gazebo bridge (topics: cmd_vel, odom, sensors, etc.)
    bridge = TimerAction(
        period=18.0,
        actions=[
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource([
                    PathJoinSubstitution([
                        FindPackageShare("turtlebot4_gz_bringup"),
                        "launch",
                        "ros_gz_bridge.launch.py",
                    ])
                ]),
                launch_arguments={
                    "model": model,
                    "namespace": namespace,
                }.items(),
            )
        ],
    )

    # TurtleBot4 nodes (HMI etc)
    tb4_nodes = TimerAction(
        period=24.0,
        actions=[
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource([
                    PathJoinSubstitution([
                        FindPackageShare("turtlebot4_gz_bringup"),
                        "launch",
                        "turtlebot4_nodes.launch.py",
                    ])
                ]),
                launch_arguments={
                    "model": model,
                    "namespace": namespace,
                }.items(),
            )
        ],
    )

    # Spawner for diffdrive_controller.
    # Runs after turtlebot4_spawn has loaded the ros2_control hardware interface.
    # --controller-manager-timeout 60 retries until controller_manager is ready.
    # This replaces the manual `ros2 control set_controller_state` workaround.
    diffdrive_spawner = TimerAction(
        period=30.0,
        actions=[
            Node(
                package="controller_manager",
                executable="spawner",
                name="diffdrive_spawner",
                arguments=[
                    "diffdrive_controller",
                    "--controller-manager", "/controller_manager",
                    "--controller-manager-timeout", "60",
                ],
                output="screen",
                parameters=[{"use_sim_time": True}],
            )
        ],
    )

    return LaunchDescription([
        declare_world,
        declare_model,
        declare_namespace,
        gz_server,
        clock_bridge,       # t=5s:  /clock bridge so controller_manager gets sim time
        spawn,              # t=8s:  spawn robot
        bridge,             # t=18s: full ros_gz_bridge
        tb4_nodes,          # t=24s: turtlebot4 nodes
        diffdrive_spawner,  # t=30s: activate diffdrive_controller
    ])