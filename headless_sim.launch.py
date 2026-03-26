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

    # ROS-Gazebo bridge
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

    return LaunchDescription([
        declare_world,
        declare_model,
        declare_namespace,
        gz_server,
        spawn,
        bridge,
        tb4_nodes,
    ])