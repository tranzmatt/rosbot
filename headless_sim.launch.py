"""
headless_sim.launch.py

Launches TurtleBot4 simulation server-only (no GUI process).
Uses gz sim -s directly so there is no Ogre/Qt GUI process to crash.
The GUI can connect remotely from a laptop via: gz sim -g

Set ROSBOT_WORLD_SDF env var to override the world SDF path (e.g. a patched copy).
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
        default_value="depot",
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

    # Allow entrypoint to inject a patched world SDF (e.g. with ogre2 sensors plugin)
    # via environment variable. Falls back to the standard turtlebot4_gz_bringup path.
    world_sdf = os.environ.get(
        "ROSBOT_WORLD_SDF",
        None
    )
    if world_sdf is None:
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

    # Clock bridge: Gazebo /world/<name>/clock → ROS2 /clock
    # Must start before spawn so controller_manager gets sim time.
    clock_bridge = TimerAction(
        period=5.0,
        actions=[
            Node(
                package="ros_gz_bridge",
                executable="parameter_bridge",
                name="clock_bridge",
                arguments=[["/world/", world, "/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock"]],
                remappings=[(["/world/", world, "/clock"], "/clock")],
                output="screen",
                parameters=[{"use_sim_time": True}],
            )
        ],
    )

    # Spawn TurtleBot4 into the world
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

    # ROS-Gazebo bridge (cmd_vel, odom, sensors, etc.)
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

    # Spawner for diffdrive_controller — handles configure+activate with retries.
    # TB4's own spawner sometimes races and fails; this recovers gracefully.
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
        clock_bridge,       # t=5s:  /clock bridge
        spawn,              # t=8s:  spawn robot
        bridge,             # t=18s: full ros_gz_bridge
        tb4_nodes,          # t=24s: turtlebot4 nodes
        diffdrive_spawner,  # t=30s: activate diffdrive_controller
    ])
